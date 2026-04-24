from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from app.api.v1 import auth, requestor, approver, accountant, profile, admin, department, notifications

app = FastAPI(title="Enterprise Expense Manager", version="1.0.0")

# Custom exception handler for validation errors
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    # Extract the first error message
    errors = exc.errors()
    if errors:
        first_error = errors[0]
        # Get the error message, removing "Value error, " prefix if present
        error_msg = first_error.get('msg', 'Validation error')
        if error_msg.startswith('Value error, '):
            error_msg = error_msg.replace('Value error, ', '')
        
        return JSONResponse(
            status_code=422,
            content={"detail": error_msg}
        )
    return JSONResponse(
        status_code=422,
        content={"detail": "Validation error"}
    )

# CORS Settings for Frontend connection
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(auth.router)
app.include_router(requestor.router)
app.include_router(approver.router)
app.include_router(accountant.router)
app.include_router(profile.router)
app.include_router(admin.router)
app.include_router(department.router)
app.include_router(notifications.router)

@app.get("/")
async def health_check():
    return {"status": "online", "system": "Expense Management Backend"}