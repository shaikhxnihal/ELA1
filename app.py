from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from cryptography.fernet import Fernet
import sqlite3
import jwt
import datetime
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from passlib.context import CryptContext
from starlette.middleware.cors import CORSMiddleware

# Initialize app and security modules
app = FastAPI()
# CORS Middleware to allow requests from all origins or specific origins (adjust accordingly)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins, adjust if needed
    allow_credentials=True,
    allow_methods=["*"],  # Allows all HTTP methods (GET, POST, OPTIONS, etc.)
    allow_headers=["*"],  # Allows all headers
)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = "your_jwt_secret_key"
ALGORITHM = "HS256"

# Database setup
DB_FILE = "keys.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        key TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    conn.commit()
    conn.close()

init_db()

# Models
class User(BaseModel):
    username: str
    password: str

class EncryptRequest(BaseModel):
    key_id: int
    plaintext: str

class DecryptRequest(BaseModel):
    key_id: int
    ciphertext: str

# Utility functions
def authenticate_user(username, password):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, password FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()
    if user and pwd_context.verify(password, user[1]):
        return user[0]
    return None

def create_access_token(data: dict, expires_delta: int = 15):
    to_encode = data.copy()
    expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=expires_delta)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# Routes
@app.get("/")
def read_root():
    return {"message": "Welcome to the Secure Key Management API"}

@app.post("/register")
def register(user: User):
    hashed_password = pwd_context.hash(user.password)
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (user.username, hashed_password))
        conn.commit()
        conn.close()
        return {"message": "User registered successfully"}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Username already exists")

@app.post("/token")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user_id = authenticate_user(form_data.username, form_data.password)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid credentials")
    token = create_access_token({"sub": form_data.username})
    return {"access_token": token, "token_type": "bearer"}

@app.post("/generate")
def generate_key(token: str = Depends(oauth2_scheme)):
    user_id = authenticate_user(jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])["sub"], None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    key = Fernet.generate_key()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO keys (user_id, key) VALUES (?, ?)", (user_id, key.decode()))
    conn.commit()
    conn.close()
    return {"key": key.decode()}

@app.post("/encrypt")
def encrypt(request: EncryptRequest, token: str = Depends(oauth2_scheme)):
    user_id = authenticate_user(jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])["sub"], None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT key FROM keys WHERE id = ? AND user_id = ?", (request.key_id, user_id))
    key = cursor.fetchone()
    conn.close()
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")
    f = Fernet(key[0].encode())
    ciphertext = f.encrypt(request.plaintext.encode())
    return {"ciphertext": ciphertext.decode()}

@app.post("/decrypt")
def decrypt(request: DecryptRequest, token: str = Depends(oauth2_scheme)):
    user_id = authenticate_user(jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])["sub"], None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT key FROM keys WHERE id = ? AND user_id = ?", (request.key_id, user_id))
    key = cursor.fetchone()
    conn.close()
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")
    f = Fernet(key[0].encode())
    plaintext = f.decrypt(request.ciphertext.encode())
    return {"plaintext": plaintext.decode()}

# Run with: uvicorn app:app --reload
