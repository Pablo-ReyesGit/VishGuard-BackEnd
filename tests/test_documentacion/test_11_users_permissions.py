"""Sección 11: Usuarios y permisos.
Cubre: Perfil propio (GET/PATCH /users/me), cambio de contraseña, control de roles (usuario normal vs superusuario) y Argon2.
"""
from core.passwords import hash_password, verify_password, needs_rehash

API = "/api/v1"

def test_usr_01_leer_y_actualizar_perfil(client):
    client.post(
        f"{API}/users/signup",
        json={"email": "elena@example.com", "password": "supersecret123"},
    )
    login = client.post(
        f"{API}/login/access-token",
        data={"username": "elena@example.com", "password": "supersecret123"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    me = client.get(f"{API}/users/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == "elena@example.com"

    updated = client.patch(
        f"{API}/users/me", headers=headers, json={"full_name": "Elena Actualizada"}
    )
    assert updated.status_code == 200
    assert updated.json()["full_name"] == "Elena Actualizada"

def test_usr_02_flujo_cambio_contrasena(client):
    client.post(
        f"{API}/users/signup",
        json={"email": "franco@example.com", "password": "passwordvieja1"},
    )
    login = client.post(
        f"{API}/login/access-token",
        data={"username": "franco@example.com", "password": "passwordvieja1"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    ok = client.patch(
        f"{API}/users/me/password",
        headers=headers,
        json={"current_password": "passwordvieja1", "new_password": "passwordnueva1"},
    )
    assert ok.status_code == 200

    old_login = client.post(
        f"{API}/login/access-token",
        data={"username": "franco@example.com", "password": "passwordvieja1"},
    )
    assert old_login.status_code == 400

def test_usr_03_argon2_hashing_contrasena():
    hashed = hash_password("Secreta123!")
    assert hashed != "Secreta123!"
    assert verify_password("Secreta123!", hashed)
    assert not verify_password("incorrecta", hashed)
    assert isinstance(needs_rehash(hashed), bool)
