# ACMAIS LINK

Aplicativo desktop para reunir os acessos de várias empresas aos respectivos ambientes do SharePoint. O aplicativo mantém documentos no SharePoint, salva identificação e links no perfil local e envia as senhas ao cofre nativo do sistema operacional. Links compartilhados também devem ser tratados como informação confidencial.

## Distribuição

Versão pública atual: [1.1.3](https://github.com/acmaiscont/acmaislink/releases/tag/v1.1.3).
O [download direto de Instalar-ACMAIS-LINK.exe](https://github.com/acmaiscont/acmaislink/releases/latest/download/Instalar-ACMAIS-LINK.exe)
acompanha a versão pública mais recente.
O instalador inclui o bootstrapper oficial do WebView2. Se o runtime estiver
ausente, o bootstrapper baixa e instala o componente silenciosamente pela internet.
O aplicativo instalado consulta e baixa atualizações em segundo plano e aplica a atualização ao fechar.
Consulte [preparação de lançamento](docs/RELEASE.md),
[alterações](CHANGELOG.md) e [segurança](SECURITY.md).

## Estado do MVP

- cadastro por link, edição, busca e exclusão de empresas;
- extração automática de código e nome pelo padrão `código - nome da empresa`;
- cadastro de várias empresas por um único link de grupo do SharePoint;
- descoberta de novas empresas ao abrir documentos do grupo, com opção de atualização manual;
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

O Microsoft WebView2 Runtime deve estar instalado para executar o aplicativo.
O instalador do ACMAIS LINK configura o componente quando necessário.

Erros capturados durante a inicialização são registrados em
`%TEMP%\ACMAIS_LINK_startup_error.log`. A
[matriz de testes](docs/TEST_MATRIX.md) descreve o diagnóstico de tela branca
observado no Windows Sandbox.

## Candidatos para macOS e Linux

A portabilidade parte da 1.1.3. O GitHub Actions gera candidatos para macOS 15
(Apple Silicon e Intel) e Ubuntu 24.04 (x64). A [instalação de homologação](docs/INSTALLATION.md#candidatos-para-macos-e-linux)
lista as dependências e a [matriz de testes](docs/TEST_MATRIX.md#portabilidade)
define o que precisa passar antes de disponibilizar downloads aos clientes.

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
Para gerar o instalador, execute `scripts/prepare-tools.ps1` e `scripts/package.ps1`.

## Dados locais

No Windows, o perfil fica em `%APPDATA%\ACMAIS\ACMAIS LINK`. O arquivo `companies.json` contém links compartilhados. As credenciais são mantidas pelo Windows Credential Manager por meio da biblioteca `keyring`.

Consulte também [arquitetura](docs/ARCHITECTURE.md), [configuração](docs/CONFIGURATION.md), [instalação](docs/INSTALLATION.md) e [matriz de testes](docs/TEST_MATRIX.md).
