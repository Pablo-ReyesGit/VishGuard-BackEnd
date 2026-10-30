"""
Tests del módulo de autenticación JWT (signup, login, perfil, contraseñas,
control de acceso de superusuario).

Ejecutar con:  pytest -v
"""


API = "/api/v1"


def test_inicio_sesion_crear_usuario(client):
    response = client.post(
        f"{API}/users/signup",
        json={"email": "ana@example.com", "password": "supersecret123", "full_name": "Ana"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "ana@example.com"
    assert data["full_name"] == "Ana"
    # nunca debe filtrarse la contraseña ni su hash en la respuesta pública
    assert "password" not in data
    assert "hashed_password" not in data


def test_inicio_sesion_usuario_duplicado_rechazado(client):
    payload = {"email": "dup@example.com", "password": "supersecret123"}
    first = client.post(f"{API}/users/signup", json=payload)
    second = client.post(f"{API}/users/signup", json=payload)
    assert first.status_code == 200
    assert second.status_code == 400


def test_login_retorno_exitoso_token(client):
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


def test_login_contrasena_incorrecta_rechazada(client):
    client.post(
        f"{API}/users/signup",
        json={"email": "carla@example.com", "password": "correcthorse1"},
    )
    response = client.post(
        f"{API}/login/access-token",
        data={"username": "carla@example.com", "password": "password-incorrecta"},
    )
    assert response.status_code == 400


def test_login_correo_inexistente_rechazado(client):
    response = client.post(
        f"{API}/login/access-token",
        data={"username": "no-existe@example.com", "password": "cualquiera123"},
    )
    assert response.status_code == 400


def test_test_token_endpoint_con_token_valido(client):
    client.post(
        f"{API}/users/signup",
        json={"email": "dario@example.com", "password": "supersecret123"},
    )
    login = client.post(
        f"{API}/login/access-token",
        data={"username": "dario@example.com", "password": "supersecret123"},
    )
    token = login.json()["access_token"]

    response = client.post(
        f"{API}/login/test-token", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["email"] == "dario@example.com"


def test_proteccion_rutas_rechazo_token_invalido(client):
    response = client.get(
        f"{API}/users/me", headers={"Authorization": "Bearer token-completamente-invalido"}
    )
    assert response.status_code == 403


def test_proteccion_rutas_rechazo_token_faltante(client):
    response = client.get(f"{API}/users/me")
    assert response.status_code == 401  # OAuth2PasswordBearer exige el header


def test_leer_perfil_usuario_actualizar(client):
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


def test_flujo_cambio_contrasena(client):
    client.post(
        f"{API}/users/signup",
        json={"email": "franco@example.com", "password": "passwordvieja1"},
    )
    login = client.post(
        f"{API}/login/access-token",
        data={"username": "franco@example.com", "password": "passwordvieja1"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # rechaza si la contraseña actual está mal
    wrong_current = client.patch(
        f"{API}/users/me/password",
        headers=headers,
        json={"current_password": "no-es-esta", "new_password": "passwordnueva1"},
    )
    assert wrong_current.status_code == 400

    # rechaza si la nueva es igual a la actual
    same_password = client.patch(
        f"{API}/users/me/password",
        headers=headers,
        json={"current_password": "passwordvieja1", "new_password": "passwordvieja1"},
    )
    assert same_password.status_code == 400

    # cambio válido
    ok = client.patch(
        f"{API}/users/me/password",
        headers=headers,
        json={"current_password": "passwordvieja1", "new_password": "passwordnueva1"},
    )
    assert ok.status_code == 200

    # la contraseña vieja ya no debe servir para loguear
    old_login = client.post(
        f"{API}/login/access-token",
        data={"username": "franco@example.com", "password": "passwordvieja1"},
    )
    assert old_login.status_code == 400

    # la nueva sí debe funcionar -> confirma que hashed_password se actualizó de verdad
    new_login = client.post(
        f"{API}/login/access-token",
        data={"username": "franco@example.com", "password": "passwordnueva1"},
    )
    assert new_login.status_code == 200


def test_usuario_normal_no_puede_listar_usuarios(client):
    client.post(
        f"{API}/users/signup",
        json={"email": "normal@example.com", "password": "supersecret123"},
    )
    login = client.post(
        f"{API}/login/access-token",
        data={"username": "normal@example.com", "password": "supersecret123"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.get(f"{API}/users/", headers=headers)
    assert response.status_code == 403


def test_superusuario_puede_listar_usuarios(client, session):
    # Creamos el superusuario directo contra la sesión de prueba, sin pasar
    # por el endpoint (que requiere ya ser superusuario -> huevo y gallina).
    from crud_user import create_user
    from schemas.user import UserCreate

    create_user(
        session=session,
        user_create=UserCreate(
            email="admin-test@example.com",
            password="adminsecret1",
            is_superuser=True,
        ),
    )

    login = client.post(
        f"{API}/login/access-token",
        data={"username": "admin-test@example.com", "password": "adminsecret1"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.get(f"{API}/users/", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["count"] >= 1


def test_superusuario_no_puede_eliminarse(client, session):
    from crud_user import create_user
    from schemas.user import UserCreate

    create_user(
        session=session,
        user_create=UserCreate(
            email="admin2@example.com",
            password="adminsecret1",
            is_superuser=True,
        ),
    )
    login = client.post(
        f"{API}/login/access-token",
        data={"username": "admin2@example.com", "password": "adminsecret1"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.delete(f"{API}/users/me", headers=headers)
    assert response.status_code == 403