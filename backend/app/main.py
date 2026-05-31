import os  # Python module for OS-related work like environment variables, file paths, etc.

from dotenv import load_dotenv  # Used to load values from the .env file

load_dotenv()  # Reads .env file and makes those values available to the backend


from fastapi import FastAPI  # Main class used to create a FastAPI backend app

from fastapi.middleware.cors import CORSMiddleware
# CORS allows frontend and backend to communicate
# Example:
# Frontend: http://localhost:5173
# Backend:  http://localhost:8000
from app.api.upload import router as upload_router

from app.api.chat import router as chat_router
# Import router from app/api/chat.py
# router = group of API routes like /chat, /sessions, /files, etc.
# We rename it to chat_router for clarity


from app.database.db import init_db
# init_db is a function that initializes the database
# It may create tables if they do not already exist


# Create the main FastAPI application
app = FastAPI(title="Materia Production Backend")


# Add CORS middleware
# This gives permission for frontend to call backend APIs
app.add_middleware(
    CORSMiddleware,

    allow_origins=["*"],
    # "*" means any frontend can call this backend
    # Good for development
    # In production, use only your frontend domain

    allow_credentials=True,
    # Allows cookies/auth credentials if needed

    allow_methods=["*"],
    # Allows all HTTP methods:
    # GET, POST, PUT, DELETE, PATCH, etc.

    allow_headers=["*"],
    # Allows all request headers
)


# This function runs automatically when backend starts
@app.on_event("startup")
async def startup():
    # Initialize database before backend starts handling requests
    await init_db()


# Attach all routes from chat.py to this main app
# Because prefix="/api", every route inside chat.py starts with /api
#
# Example:
# In chat.py: @router.post("/chat")
# Final URL:  POST /api/chat
#
# In chat.py: @router.get("/sessions")
# Final URL:  GET /api/sessions
app.include_router(chat_router, prefix="/api")
app.include_router(upload_router, prefix='/api') 

# Simple test route
# Open http://localhost:8000/ in browser
# It should return: {"message": "Materia backend is running"}
@app.get("/")
def root():
    return {"message": "Materia backend is running"}