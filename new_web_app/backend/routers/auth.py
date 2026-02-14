"""
Authentication Router for FastAPI Backend

Provides:
- POST /auth/login - Authenticate and get JWT token
- POST /auth/register - Create new user
- GET /auth/me - Get current user from token
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from datetime import datetime, timedelta
from typing import Optional
import hashlib
import jwt
import os

from ..auth_models import UserCreate, UserLogin, UserResponse, Token, TokenData
from ..database import get_db_connection

router = APIRouter(prefix="/auth", tags=["Authentication"])

# JWT Configuration
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 1 week

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

def hash_password(password: str) -> str:
    """SHA256 hash matching the legacy app format"""
    return hashlib.sha256(password.encode()).hexdigest()

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> TokenData:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        # Convert sub back to int (was stored as string for JWT compatibility)
        sub = payload.get("sub")
        user_id = int(sub) if sub else None
        return TokenData(
            user_id=user_id,
            username=payload.get("username"),
            role=payload.get("role")
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")

async def get_current_user(token: str = Depends(oauth2_scheme)) -> TokenData:
    """Dependency to get current user from JWT token"""
    return decode_token(token)

async def require_admin(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    """Dependency to require admin role"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

@router.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """Authenticate user and return JWT token"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username = ?", (form_data.username,))
    user = c.fetchone()
    conn.close()
    
    if not user or user["password_hash"] != hash_password(form_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create JWT token - sub must be string for PyJWT compatibility
    access_token = create_access_token(
        data={
            "sub": str(user["id"]),
            "username": user["username"],
            "role": user["role"]
        }
    )
    
    return Token(access_token=access_token)

@router.post("/register", response_model=UserResponse)
async def register(user_data: UserCreate):
    """Create a new user account"""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Check if username exists
    c.execute("SELECT id FROM users WHERE username = ?", (user_data.username,))
    if c.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Username already exists")
    
    # Create user
    c.execute(
        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?) RETURNING id",
        (user_data.username, hash_password(user_data.password), "user"),
    )
    inserted = c.fetchone()
    user_id = None
    if inserted:
        try:
            user_id = int(inserted["id"])
        except Exception:
            user_id = int(inserted[0])
    conn.commit()
    conn.close()
    
    return UserResponse(id=user_id, username=user_data.username, role="user")

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: TokenData = Depends(get_current_user)):
    """Get current authenticated user info"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, username, role FROM users WHERE id = ?", (current_user.user_id,))
    user = c.fetchone()
    conn.close()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return UserResponse(id=user["id"], username=user["username"], role=user["role"])
