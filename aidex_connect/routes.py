import os
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

# Create a router specifically for the Aidex connection endpoints
router = APIRouter(prefix="/aidex")

# Point Jinja2 to look directly inside your aidex-connect directory for the HTML file
templates = Jinja2Templates(directory="aidex-connect")

# This creates the frontend webpage route: https://onrender.com{user_token}
@router.get("/connect/{user_token}", response_class=HTMLResponse)
async def serve_connect_page(request: Request, user_token: str):
    # Pass the user's phone token to the HTML template so the blue button can use it
    return templates.TemplateResponse("connect.html", {"request": request, "user_token": user_token})

# This creates your final landing/handshake route: https://onrender.com
@router.get("/callback")
async def aidex_callback(code: str, state: str):
    # 'state' contains the user_token you passed earlier.
    # 'code' is what you will swap for an access token to read their CGM metrics.
    return {"status": "Successfully connected your CGM to Travenhealth! You can close this screen."}
