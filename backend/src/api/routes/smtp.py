from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from src.models.user import User, UserRole
from src.models.smtp_config import SMTPConfig
from src.db.session import get_db
from src.schemas.smtp_config import SmtpConfigResponse, SmtpConfigCreate, SmtpConfigUpdate, SmtpConfigTest
from src.api.deps import require_roles
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

router = APIRouter()

@router.post("", response_model=SmtpConfigResponse, include_in_schema=False)
@router.post("/", response_model=SmtpConfigResponse)
def create_smtp_config(
    payload: SmtpConfigCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
):
    existing = db.query(SMTPConfig).filter(SMTPConfig.username == payload.username).filter(SMTPConfig.host == payload.host).first()
    if existing:
        raise HTTPException(status_code=400, detail="SMTP configuration with this host and username already exists")
    config = SMTPConfig(
        name=payload.name.strip(),
        host=payload.host.strip(),
        port=payload.port,
        username=payload.username.strip(),
        password=payload.password,
        from_email=payload.from_email,
        from_name=payload.from_name.strip(),
        use_tls=payload.use_tls,
        is_active=False,  # New configs are inactive by default
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config

@router.get("", response_model=list[SmtpConfigResponse], include_in_schema=False)
@router.get("/", response_model=list[SmtpConfigResponse])
def get_smtp_config(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
):
    config = db.query(SMTPConfig).all()
    return config


@router.put("/{smtp_config_id}", response_model=SmtpConfigResponse)
def update_smtp_config(
    smtp_config_id: int,
    payload: SmtpConfigUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
):
    config = db.query(SMTPConfig).filter(SMTPConfig.id == smtp_config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="SMTP configuration not found")
    effective_host = payload.host if payload.host is not None else config.host
    effective_username = payload.username if payload.username is not None else config.username
    existing = (
        db.query(SMTPConfig)
        .filter(SMTPConfig.id != smtp_config_id)
        .filter(SMTPConfig.username == effective_username)
        .filter(SMTPConfig.host == effective_host)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Another SMTP configuration with this host and username already exists")
    if payload.name is not None:
        config.name = payload.name.strip()
    if payload.host is not None:
        config.host = payload.host.strip()
    if payload.port is not None:
        config.port = payload.port
    if payload.username is not None:
        config.username = payload.username.strip()
    if payload.password is not None:
        config.password = payload.password
    if payload.from_email is not None:
        config.from_email = payload.from_email
    if payload.from_name is not None:
        config.from_name = payload.from_name.strip()
    if payload.use_tls is not None:
        config.use_tls = payload.use_tls
    db.commit()
    db.refresh(config)
    return config

@router.delete("/{smtp_config_id}", response_model=dict)
def delete_smtp_config(
    smtp_config_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
):
    config = db.query(SMTPConfig).filter(SMTPConfig.id == smtp_config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="SMTP configuration not found")
    if config.is_active is True:
        raise HTTPException(status_code=400, detail="Cannot delete an active SMTP configuration. Please activate another configuration before deleting this one.")
    db.delete(config)
    db.commit()
    return {"detail": "SMTP configuration deleted successfully"}

@router.post("/{smtp_config_id}/activate", response_model=SmtpConfigResponse)
def activate_smtp_config(
    smtp_config_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
):
    config = db.query(SMTPConfig).filter(SMTPConfig.id == smtp_config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="SMTP configuration not found")
    # Deactivate all other configs
    db.query(SMTPConfig).update({SMTPConfig.is_active: False})
    # Activate the selected config
    config.is_active = True
    db.commit()
    db.refresh(config)
    return config   


@router.post("/test", response_model=dict)
def test_smtp_config(
    payload: SmtpConfigTest,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.admin)),
):

    # Fetch active SMTP config from DB (this is just a placeholder, implement actual DB fetch)
    config = db.query(SMTPConfig).filter(SMTPConfig.id == payload.id).first()
    if not config:
        raise HTTPException(status_code=404, detail="No active SMTP configuration found")
    try:
        # Create a test email message
        msg = MIMEMultipart()
        msg['From'] = config.from_email
        msg['To'] = payload.to  # Sending test email to the specified address
        msg['Subject'] = "Test Email from Invoicing System"
        msg.attach(MIMEText("This is a test email to verify SMTP configuration.", 'plain'))

        # Connect to the SMTP server and send the email
        if config.use_tls:
            server = smtplib.SMTP(config.host, config.port)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(config.host, config.port)

        server.login(config.username, config.password)
        server.send_message(msg)
        server.quit()
        return {"detail": "Test email sent successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to send test email: {str(e)}")