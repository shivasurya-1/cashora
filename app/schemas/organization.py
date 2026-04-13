from pydantic import BaseModel, EmailStr
from typing import Optional

class AdminSetupIn(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    phone_number: str

class OrganizationSetup(BaseModel):
    org_name: str
    admin_details: AdminSetupIn