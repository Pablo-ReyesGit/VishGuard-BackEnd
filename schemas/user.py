from pydantic import BaseModel, ConfigDict, EmailStr, Field


# Propiedades compartidas por todas las representaciones de usuario
#
# model_config con from_attributes=True es necesario porque en el template
# original estas clases eran SQLModel (que lo trae activado por defecto).
# Al pasarlas a pydantic.BaseModel puro, hay que activarlo a mano para que
# UserCreate.model_validate(otro_objeto) y UserPublic.model_validate(user)
# funcionen leyendo atributos en vez de exigir un dict.
class UserBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    email: EmailStr
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = None


# Creación por parte de un administrador/superusuario (puede fijar is_superuser)
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


# Registro público (endpoint /signup), sin poder marcarse como superusuario
class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = None


# Actualización por parte de un admin, todos los campos opcionales
class UserUpdate(BaseModel):
    email: EmailStr | None = None
    is_active: bool | None = None
    is_superuser: bool | None = None
    full_name: str | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


# Actualización que el propio usuario puede hacer sobre sí mismo (/me)
# No incluye is_active/is_superuser: un usuario no puede auto-promoverse
class UserUpdateMe(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None


# Cambio de contraseña propio (requiere confirmar la actual)
class UpdatePassword(BaseModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Propiedades públicas devueltas al cliente — nunca incluye hashed_password
class UserPublic(UserBase):
    id: int


# Listado paginado de usuarios (respuesta de GET /users/)
class UsersPublic(BaseModel):
    data: list[UserPublic]
    count: int