from pydantic import BaseModel, Field
 
 
# JSON payload que se devuelve al hacer login exitoso
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
 
 
# Contenido decodificado del JWT (lo que va dentro del "sub")
class TokenPayload(BaseModel):
    sub: str | None = None
 
 
# Body para el endpoint de reset de contraseña vía token de un solo uso
class NewPassword(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
 
 
# Respuesta genérica de mensaje, usada por varios endpoints (login, users)
class Message(BaseModel):
    message: str
 