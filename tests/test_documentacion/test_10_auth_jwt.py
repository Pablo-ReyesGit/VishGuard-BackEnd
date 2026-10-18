"""Sección 10: Registro e inicio de sesión (JWT).
Cubre: Signup, duplicados, login exitoso o incorrecto, tokens de acceso Bearer y validación de autenticación.
"""
API = "/api/v1"

def test_auth_01_crear_usuario(client):
    response = client.post(
        f"{API}/users/signup",
        json={"email": "ana@example.com", "password": "supersecret123", "full_name": "Ana"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "ana@example.com"
    assert "password" not in data and "hashed_password" not in data

def test_auth_02_usuario_duplicado_rechazado(client):
    payload = {"email": "dup@example.com", "password": "supersecret123"}
    first = client.post(f"{API}/users/signup", json=payload)
    second = client.post(f"{API}/users/signup", json=payload)
    assert first.status_code == 200
    assert second.status_code == 400

def test_auth_03_login_retorno_exitoso_token(client):
    client.post(
        f"{API}/users/signup",
        json={"email": "bob@example.com", "password": "correcthorse1"},
    )
    response = client.post(
        f"{API}/login/access-token",
        data={"username": "bob@example.com", "password": "correcthorse1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) > 0

def test_auth_04_login_contrasena_incorrecta(client):
    client.post(
        f"{API}/users/signup",
        json={"email": "carla@example.com", "password": "correcthorse1"},
    )
    response = client.post(
        f"{API}/login/access-token",
        data={"username": "carla@example.com", "password": "password-incorrecta"},
    )
    assert response.status_code == 400

def test_auth_05_proteccion_rutas_rechazo_token_invalido(client):
    response = client.get(
        f"{API}/users/me", headers={"Authorization": "Bearer token-completamente-invalido"}
    )
    assert response.status_code == 403
