from fastapi.testclient import TestClient


def test_list_events_empty(client: TestClient) -> None:
    response = client.get("/api/events")
    assert response.status_code == 200
    assert response.json() == []
