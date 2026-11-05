# Companies, roles and team

## Run more than one company

The **Company** switcher is at the top of the sidebar. Click a company to switch to it. Your choice is saved on your account, so it follows you across devices.

To add one, click **+ New Company**, enter a name and, if you have one, a GSTIN, then complete its details in [Settings → Company](./company-setup). A new company starts with the currency set to INR and no address, so check the currency and fill in the address.

Each company keeps its own invoices, ledgers, products, numbering, financial years, bank accounts, API keys and email history.

| | Hosted version | Self-hosted |
|---|---|---|
| Companies you can create | Up to 3 | One by default. An administrator can raise the limit in the database. |

## Roles

| Task | Admin | Manager | Staff |
|---|---|---|---|
| View lists, reports, ledgers and products | ✓ | ✓ | ✓ |
| Create, edit and cancel invoices, quotations and credit notes | ✓ | ✓ | ✓ |
| Change your own password, shortcuts and theme | ✓ | ✓ | ✓ |
| Create, edit and delete ledgers | ✓ | ✓ | |
| Create, edit, import and delete products, and adjust stock | ✓ | ✓ | |
| Record production and edit bills of materials | ✓ | ✓ | |
| Record, edit and cancel payments | ✓ | ✓ | |
| Send invoices, statements and reminders by email | ✓ | ✓ | |
| Publish marketplace listings and handle orders | ✓ | ✓ | |
| Save company details, logo and terms | ✓ | ✓ | |
| Switch or add financial years | ✓ | | |
| Edit invoice series | ✓ | | |
| Manage API keys and see email history | ✓ | | |
| Connect to a marketplace | ✓ | | |

Staff may still see buttons for things they cannot do. The app refuses the action with "Insufficient permissions".

The sidebar shows your role as **Admin** or **User**. Managers and staff both show as User.

## Add team members

**The app does not yet have a screen for inviting people.**

- **Hosted version:** whoever creates a company becomes its admin. There is currently no way to add another person to that company.
- **Self-hosted:** an admin creates users through the API with `POST /api/users`, using the interactive docs at `/docs`. Supply an email, full name, password of at least 8 characters, and a role. The new user can sign in immediately and can reach every company with that role.

There is also no screen for deactivating a user.
