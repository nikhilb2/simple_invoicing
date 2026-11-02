"""Tests for BOM cost, cycle, requirement, and inventory validation helpers."""

from decimal import Decimal

import pytest

from src.models.bom import BillOfMaterial
from src.models.company import CompanyProfile
from src.models.inventory import Inventory
from src.models.product import Product
from src.services.bom_service import (
    CircularBOMError,
    calculate_bom_cost_recursive,
    execute_production,
    get_bom_requirements,
    validate_bom_availability,
    validate_no_circular_bom,
)


@pytest.fixture
def company(db_session):
    company = CompanyProfile(name="BOM Test Co", address="123 Test St")
    db_session.add(company)
    db_session.flush()
    return company


def make_product(db, company_id, sku, *, price="0", **kwargs):
    product = Product(
        company_id=company_id,
        sku=sku,
        name=sku,
        price=Decimal(price),
        **kwargs,
    )
    db.add(product)
    db.flush()
    return product


def add_component(db, company_id, product_id, component_id, quantity="1"):
    entry = BillOfMaterial(
        company_id=company_id,
        product_id=product_id,
        component_product_id=component_id,
        quantity_required=Decimal(quantity),
    )
    db.add(entry)
    db.flush()
    return entry


def make_inventory(db, company_id, product_id, quantity):
    inventory = Inventory(
        company_id=company_id,
        product_id=product_id,
        quantity=Decimal(quantity),
    )
    db.add(inventory)
    db.flush()
    return inventory


class TestCalculateBomCostRecursive:
    def test_no_components_costs_zero(self, db_session, company):
        product = make_product(db_session, company.id, "FINISHED", price="99")

        assert calculate_bom_cost_recursive(db_session, company.id, product.id) == Decimal("0")

    def test_sums_component_prices_with_fractional_quantities(self, db_session, company):
        product = make_product(db_session, company.id, "FINISHED", is_producable=True)
        first = make_product(db_session, company.id, "FIRST", price="1.25")
        second = make_product(db_session, company.id, "SECOND", price="0.10")
        add_component(db_session, company.id, product.id, first.id, "2.4")
        add_component(db_session, company.id, product.id, second.id, "3")

        cost = calculate_bom_cost_recursive(db_session, company.id, product.id)

        assert isinstance(cost, Decimal)
        assert cost == Decimal("3.30")

    @pytest.mark.parametrize("production_cost", ["0", "4.25"])
    def test_stored_production_cost_overrides_price_and_nested_bom(
        self, db_session, company, production_cost
    ):
        product = make_product(db_session, company.id, "FINISHED", is_producable=True)
        assembly = make_product(
            db_session, company.id, "ASSEMBLY", price="999",
            is_producable=True, production_cost=Decimal(production_cost),
        )
        raw = make_product(db_session, company.id, "RAW", price="100")
        add_component(db_session, company.id, product.id, assembly.id, "2")
        add_component(db_session, company.id, assembly.id, raw.id, "3")

        assert calculate_bom_cost_recursive(
            db_session, company.id, product.id
        ) == Decimal(production_cost) * 2

    def test_recurses_when_assembly_has_no_stored_cost(self, db_session, company):
        product = make_product(db_session, company.id, "FINISHED", is_producable=True)
        assembly = make_product(
            db_session, company.id, "ASSEMBLY", price="999", is_producable=True
        )
        raw = make_product(db_session, company.id, "RAW", price="4.50")
        packaging = make_product(db_session, company.id, "PACKAGING", price="1.25")
        add_component(db_session, company.id, product.id, assembly.id, "2")
        add_component(db_session, company.id, assembly.id, raw.id, "3")
        add_component(db_session, company.id, product.id, packaging.id)

        assert calculate_bom_cost_recursive(
            db_session, company.id, product.id
        ) == Decimal("28.25")

    def test_shared_subassembly_is_counted_in_each_branch(self, db_session, company):
        product, left, right, shared = [
            make_product(db_session, company.id, sku, is_producable=True)
            for sku in ("FINISHED", "LEFT", "RIGHT", "SHARED")
        ]
        raw = make_product(db_session, company.id, "RAW", price="1.25")
        add_component(db_session, company.id, product.id, left.id, "2")
        add_component(db_session, company.id, product.id, right.id, "3")
        add_component(db_session, company.id, left.id, shared.id, "4")
        add_component(db_session, company.id, right.id, shared.id, "5")
        add_component(db_session, company.id, shared.id, raw.id, "2")

        # Shared costs 2.50; the two branches cost 2 * 10 + 3 * 12.50.
        assert calculate_bom_cost_recursive(
            db_session, company.id, product.id
        ) == Decimal("57.50")

    def test_existing_cycle_does_not_hide_other_component_costs(self, db_session, company):
        product = make_product(db_session, company.id, "FINISHED", is_producable=True)
        assembly = make_product(db_session, company.id, "ASSEMBLY", is_producable=True)
        raw = make_product(db_session, company.id, "RAW", price="2")
        add_component(db_session, company.id, product.id, assembly.id, "2")
        add_component(db_session, company.id, assembly.id, product.id)
        add_component(db_session, company.id, assembly.id, raw.id, "3")

        assert calculate_bom_cost_recursive(
            db_session, company.id, product.id
        ) == Decimal("12")

    def test_missing_component_is_skipped(self, db_session, company):
        product = make_product(db_session, company.id, "FINISHED", is_producable=True)
        raw = make_product(db_session, company.id, "RAW", price="2.50")
        # The shared SQLite fixture permits orphan rows to exercise this guard.
        add_component(db_session, company.id, product.id, 9999, "10")
        add_component(db_session, company.id, product.id, raw.id, "2")

        assert calculate_bom_cost_recursive(
            db_session, company.id, product.id
        ) == Decimal("5")

    def test_ignores_bom_from_another_company(self, db_session, company):
        other = CompanyProfile(name="Other Co", address="Other address")
        db_session.add(other)
        db_session.flush()
        product = make_product(db_session, company.id, "FINISHED", is_producable=True)
        raw = make_product(db_session, company.id, "RAW", price="10")
        add_component(db_session, company.id, product.id, raw.id, "2")

        assert calculate_bom_cost_recursive(db_session, other.id, product.id) == Decimal("0")


class TestValidateNoCircularBom:
    @pytest.mark.parametrize(
        "chain_length", [0, 1, 2], ids=["self-reference", "direct-cycle", "indirect-cycle"]
    )
    def test_rejects_cycles(self, db_session, company, chain_length):
        products = [
            make_product(db_session, company.id, f"P{index}", is_producable=True)
            for index in range(chain_length + 1)
        ]
        for parent, component in zip(products, products[1:]):
            add_component(db_session, company.id, parent.id, component.id)

        with pytest.raises(CircularBOMError, match="would create a circular BOM reference"):
            validate_no_circular_bom(
                db_session, company.id, products[-1].id, products[0].id
            )

    def test_allows_diamond_with_shared_component(self, db_session, company):
        product, assembly, left, right, shared = [
            make_product(db_session, company.id, sku, is_producable=True)
            for sku in ("FINISHED", "ASSEMBLY", "LEFT", "RIGHT", "SHARED")
        ]
        add_component(db_session, company.id, assembly.id, left.id)
        add_component(db_session, company.id, assembly.id, right.id)
        add_component(db_session, company.id, left.id, shared.id)
        add_component(db_session, company.id, right.id, shared.id)

        assert validate_no_circular_bom(
            db_session, company.id, product.id, assembly.id
        ) is None

    def test_unrelated_existing_cycle_terminates_without_rejection(self, db_session, company):
        product, first, second = [
            make_product(db_session, company.id, sku, is_producable=True)
            for sku in ("FINISHED", "FIRST", "SECOND")
        ]
        add_component(db_session, company.id, first.id, second.id)
        add_component(db_session, company.id, second.id, first.id)

        assert validate_no_circular_bom(
            db_session, company.id, product.id, first.id
        ) is None

    def test_ignores_paths_from_another_company(self, db_session, company):
        other = CompanyProfile(name="Other Co", address="Other address")
        db_session.add(other)
        db_session.flush()
        first = make_product(db_session, company.id, "FIRST", is_producable=True)
        second = make_product(db_session, company.id, "SECOND", is_producable=True)
        add_component(db_session, company.id, first.id, second.id)

        assert validate_no_circular_bom(
            db_session, other.id, second.id, first.id
        ) is None


class TestGetBomRequirements:
    @pytest.mark.parametrize(
        "quantity,first_needed,second_needed",
        [("0", "0", "0"), ("1", "1.25", "2"), ("2.4", "3", "4.8")],
    )
    def test_scales_direct_components(
        self, db_session, company, quantity, first_needed, second_needed
    ):
        product = make_product(db_session, company.id, "FINISHED", is_producable=True)
        first = make_product(db_session, company.id, "FIRST")
        second = make_product(db_session, company.id, "SECOND")
        add_component(db_session, company.id, product.id, first.id, "1.25")
        add_component(db_session, company.id, product.id, second.id, "2")

        assert get_bom_requirements(
            db_session, company.id, product.id, Decimal(quantity)
        ) == {first.id: Decimal(first_needed), second.id: Decimal(second_needed)}

    def test_does_not_expand_producable_subcomponents(self, db_session, company):
        product = make_product(db_session, company.id, "FINISHED", is_producable=True)
        assembly = make_product(db_session, company.id, "ASSEMBLY", is_producable=True)
        raw = make_product(db_session, company.id, "RAW")
        add_component(db_session, company.id, product.id, assembly.id, "2")
        add_component(db_session, company.id, assembly.id, raw.id, "5")

        assert get_bom_requirements(
            db_session, company.id, product.id, Decimal("3")
        ) == {assembly.id: Decimal("6")}

    def test_accumulates_repeated_component_rows(self, db_session, company):
        product = make_product(db_session, company.id, "FINISHED", is_producable=True)
        raw = make_product(db_session, company.id, "RAW")
        add_component(db_session, company.id, product.id, raw.id, "1.25")
        add_component(db_session, company.id, product.id, raw.id, "0.75")

        assert get_bom_requirements(
            db_session, company.id, product.id, Decimal("2")
        ) == {raw.id: Decimal("4")}

    def test_no_components_has_no_requirements(self, db_session, company):
        product = make_product(db_session, company.id, "FINISHED", is_producable=True)

        assert get_bom_requirements(db_session, company.id, product.id, Decimal("3")) == {}

    def test_ignores_bom_from_another_company(self, db_session, company):
        other = CompanyProfile(name="Other Co", address="Other address")
        db_session.add(other)
        db_session.flush()
        product = make_product(db_session, company.id, "FINISHED", is_producable=True)
        raw = make_product(db_session, company.id, "RAW")
        add_component(db_session, company.id, product.id, raw.id, "2")

        assert get_bom_requirements(db_session, other.id, product.id, Decimal("3")) == {}


class TestValidateBomAvailability:
    @pytest.mark.parametrize("stock", ["4", "5"])
    def test_sufficient_or_exact_stock_is_valid_without_consuming_it(
        self, db_session, company, stock
    ):
        product = make_product(db_session, company.id, "FINISHED", is_producable=True)
        raw = make_product(db_session, company.id, "RAW")
        add_component(db_session, company.id, product.id, raw.id, "2")
        inventory = make_inventory(db_session, company.id, raw.id, stock)

        assert validate_bom_availability(
            db_session, company.id, product.id, Decimal("2")
        ) == (True, "")
        db_session.refresh(inventory)
        assert inventory.quantity == Decimal(stock)

    def test_reports_fractional_stock_shortage(self, db_session, company):
        product = make_product(db_session, company.id, "FINISHED", is_producable=True)
        raw = make_product(db_session, company.id, "RAW")
        add_component(db_session, company.id, product.id, raw.id, "2")
        make_inventory(db_session, company.id, raw.id, "3.999")

        valid, message = validate_bom_availability(
            db_session, company.id, product.id, Decimal("2")
        )

        assert valid is False
        assert message == "Insufficient inventory for RAW: need 4.000, have 3.999"

    def test_checks_every_component(self, db_session, company):
        product = make_product(db_session, company.id, "FINISHED", is_producable=True)
        first = make_product(db_session, company.id, "FIRST")
        second = make_product(db_session, company.id, "SECOND")
        add_component(db_session, company.id, product.id, first.id)
        add_component(db_session, company.id, product.id, second.id)
        make_inventory(db_session, company.id, first.id, "10")
        make_inventory(db_session, company.id, second.id, "0")

        valid, message = validate_bom_availability(
            db_session, company.id, product.id, Decimal("1")
        )

        assert valid is False
        assert message.startswith("Insufficient inventory for SECOND:")

    @pytest.mark.parametrize("missing_product", [False, True], ids=["known-product", "orphan"])
    def test_reports_missing_inventory(self, db_session, company, missing_product):
        product = make_product(db_session, company.id, "FINISHED", is_producable=True)
        component_id = 9999
        component_sku = "Unknown"
        if not missing_product:
            component = make_product(db_session, company.id, "RAW")
            component_id = component.id
            component_sku = component.sku
        add_component(db_session, company.id, product.id, component_id)

        assert validate_bom_availability(
            db_session, company.id, product.id, Decimal("1")
        ) == (False, f"No inventory record for component: {component_sku}")

    def test_does_not_use_another_companys_inventory(self, db_session, company):
        other = CompanyProfile(name="Other Co", address="Other address")
        db_session.add(other)
        db_session.flush()
        product = make_product(db_session, company.id, "FINISHED", is_producable=True)
        raw = make_product(db_session, company.id, "RAW")
        add_component(db_session, company.id, product.id, raw.id)
        make_inventory(db_session, other.id, raw.id, "100")

        assert validate_bom_availability(
            db_session, company.id, product.id, Decimal("1")
        ) == (False, "No inventory record for component: RAW")

    def test_zero_production_needs_no_stock(self, db_session, company):
        product = make_product(db_session, company.id, "FINISHED", is_producable=True)
        raw = make_product(db_session, company.id, "RAW")
        add_component(db_session, company.id, product.id, raw.id, "2")
        make_inventory(db_session, company.id, raw.id, "0")

        assert validate_bom_availability(
            db_session, company.id, product.id, Decimal("0")
        ) == (True, "")

    def test_no_components_is_available(self, db_session, company):
        product = make_product(db_session, company.id, "FINISHED", is_producable=True)

        assert validate_bom_availability(
            db_session, company.id, product.id, Decimal("1")
        ) == (True, "")


class TestExecuteProductionGuards:
    def test_rejects_serial_tracked_product_without_touching_stock(self, db_session, company):
        product = make_product(
            db_session, company.id, "FINISHED", is_producable=True, track_serials=True
        )
        component = make_product(db_session, company.id, "RAW", price="1")
        add_component(db_session, company.id, product.id, component.id, "1")
        make_inventory(db_session, company.id, component.id, "10")

        result = execute_production(db_session, company.id, product.id, Decimal("2"), user_id=1)

        assert result["success"] is False
        assert "Serial-tracked" in result["message"]
        assert (
            db_session.query(Inventory)
            .filter(Inventory.product_id == component.id)
            .first()
            .quantity
            == Decimal("10")
        )
        assert (
            db_session.query(Inventory)
            .filter(Inventory.product_id == product.id)
            .first()
            is None
        )

    def test_rejects_serial_tracked_component_without_touching_stock(
        self, db_session, company
    ):
        product = make_product(db_session, company.id, "FINISHED", is_producable=True)
        component = make_product(
            db_session, company.id, "RAW", price="1", track_serials=True
        )
        add_component(db_session, company.id, product.id, component.id, "1")
        make_inventory(db_session, company.id, component.id, "10")

        result = execute_production(db_session, company.id, product.id, Decimal("2"), user_id=1)

        assert result["success"] is False
        assert "Serial-tracked" in result["message"]
        assert (
            db_session.query(Inventory)
            .filter(Inventory.product_id == component.id)
            .first()
            .quantity
            == Decimal("10")
        )

    def test_rejects_fractional_quantity_for_whole_number_product(self, db_session, company):
        product = make_product(
            db_session, company.id, "FINISHED", is_producable=True, allow_decimal=False
        )
        component = make_product(db_session, company.id, "RAW", price="1")
        add_component(db_session, company.id, product.id, component.id, "1")
        make_inventory(db_session, company.id, component.id, "10")

        result = execute_production(db_session, company.id, product.id, Decimal("2.5"), user_id=1)

        assert result["success"] is False
        assert result["message"] == "Quantity must be a whole number for this product"
        assert (
            db_session.query(Inventory)
            .filter(Inventory.product_id == component.id)
            .first()
            .quantity
            == Decimal("10")
        )

    def test_whole_and_decimal_quantities_still_produce(self, db_session, company):
        whole_product = make_product(
            db_session, company.id, "WHOLE", is_producable=True, allow_decimal=False
        )
        decimal_product = make_product(
            db_session, company.id, "DECIMAL", is_producable=True, allow_decimal=True
        )
        raw_a = make_product(db_session, company.id, "RAW-A", price="1")
        raw_b = make_product(db_session, company.id, "RAW-B", price="1")
        add_component(db_session, company.id, whole_product.id, raw_a.id, "1")
        add_component(db_session, company.id, decimal_product.id, raw_b.id, "1")
        make_inventory(db_session, company.id, raw_a.id, "10")
        make_inventory(db_session, company.id, raw_b.id, "10")

        ok_whole = execute_production(db_session, company.id, whole_product.id, Decimal("2"), user_id=1)
        ok_decimal = execute_production(
            db_session, company.id, decimal_product.id, Decimal("2.5"), user_id=1
        )

        assert ok_whole["success"] is True
        assert ok_decimal["success"] is True
