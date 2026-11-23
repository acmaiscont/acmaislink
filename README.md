# ACMAIS LINK

Aplicativo desktop para reunir os acessos de várias empresas aos respectivos ambientes do SharePoint. O aplicativo mantém documentos no SharePoint, salva identificação e links no perfil local e envia as senhas ao cofre nativo do sistema operacional. Links compartilhados também devem ser tratados como informação confidencial.

## Distribuição

Os instaladores são distribuídos pelo [GitHub Releases](https://github.com/acmaiscont/acmaislink/releases/latest).
O pacote `full` inclui WebView2 offline e o pacote `update` serve para quem já possui o runtime.
O aplicativo instalado consulta e baixa atualizações em segundo plano e aplica a atualização ao fechar.
Consulte [preparação de lançamento](docs/RELEASE.md),
[alterações](CHANGELOG.md) e [segurança](SECURITY.md).

## Estado do MVP

- cadastro por link, edição, busca e exclusão de empresas;
- extração automática de código e nome pelo padrão `código - nome da empresa`;
- código da empresa como identificador único;
- senha no Windows Credential Manager, Keychain ou keyring compatível;
- navegação em uma única janela com sessão persistente;
- autenticação intermediária oculta e acesso direto à pasta;
- preenchimento automático restrito a endereços HTTPS `*.sharepoint.com`;
- fallback para o navegador padrão;
- logs rotativos sem credenciais;
- envio guiado por empresa, setor, tipo e competência, com histórico local.

## Executar no Windows

```powershell
.\scripts\setup.ps1
.\scripts\run.ps1
```

O Microsoft WebView2 Runtime deve estar instalado. Ter o navegador Edge não comprova a presença do runtime; o pacote completo instala o componente quando necessário.

Se a aplicação não conseguir iniciar, ela exibirá uma mensagem e gravará o diagnóstico em `%TEMP%\ACMAIS_LINK_startup_error.log`.

## Testar

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Gerar o executável

```powershell
.\scripts\build.ps1
```

Para mudar a versão, edite apenas `__version__` em
`src/acmais_link/__init__.py` e execute a compilação. O build gera o HTML do
rodapé, o endereço local de cada versão e os metadados do executável.
O resultado fica em `release-v<versão>\ACMAIS LINK\ACMAIS LINK.exe`.
Para gerar instaladores, execute `scripts/prepare-tools.ps1` e `scripts/package.ps1`.

## Dados locais

No Windows, o perfil fica em `%APPDATA%\ACMAIS\ACMAIS LINK`. O arquivo `companies.json` contém links compartilhados. As credenciais são mantidas pelo Windows Credential Manager por meio da biblioteca `keyring`.

Consulte também [arquitetura](docs/ARCHITECTURE.md), [configuração](docs/CONFIGURATION.md), [instalação](docs/INSTALLATION.md) e [matriz de testes](docs/TEST_MATRIX.md).
