"""Check the OS credential store using a disposable test credential."""
from uuid import uuid4

from acmais_link.credential_store import CredentialStore


if __name__ == "__main__":
    account = f"acmais-link-ci-{uuid4()}"
    credential = str(uuid4())
    store = CredentialStore()
    store.set(account, credential)
    try:
        if store.get(account) != credential:
            raise RuntimeError("O cofre do sistema não retornou a credencial de teste.")
    finally:
        store.delete(account)
    print("Gravação, leitura e exclusão no cofre do sistema concluídas.")
