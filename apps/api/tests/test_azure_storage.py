from leitesol_api.infrastructure.azure_storage import BlobStorageGateway


def test_blob_storage_connection_check_reads_container_properties() -> None:
    class FakeContainer:
        called = False

        def get_container_properties(self) -> None:
            self.called = True

    gateway = object.__new__(BlobStorageGateway)
    container = FakeContainer()
    gateway._container = container

    gateway.check_connection()

    assert container.called
