# ACMAIS LINK

Aplicativo desktop para reunir os acessos de várias empresas aos respectivos ambientes do SharePoint. O aplicativo mantém documentos no SharePoint, salva identificação e links no perfil local e envia as senhas ao cofre nativo do sistema operacional. Links compartilhados também devem ser tratados como informação confidencial.

## Candidato 1.0.0 — aguardando aprovação

Os dois instaladores ficam em `artifacts/`: `full` inclui WebView2 offline;
`update` é o pacote leve para quem já possui o runtime. O aplicativo consulta
Releases públicas estáveis de https://github.com/acmaiscont/acmaislink. Na instalação
padrão, consulta e download são automáticos; a instalação é silenciosa ao fechar
a janela, sem perguntar ao usuário. Nenhuma publicação no GitHub é automática.
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
- identidade visual baseada na logo fornecida.

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

O resultado será criado em `release-v1.0.0\ACMAIS LINK\ACMAIS LINK.exe`.
Para gerar instaladores, execute `scripts/prepare-tools.ps1` e `scripts/package.ps1`.

## Dados locais

No Windows, o perfil fica em `%APPDATA%\ACMAIS\ACMAIS LINK`. O arquivo `companies.json` contém links compartilhados, mas nunca senhas. As credenciais são mantidas pelo Windows Credential Manager por meio da biblioteca `keyring`.

Consulte também [arquitetura](docs/ARCHITECTURE.md), [configuração](docs/CONFIGURATION.md), [instalação](docs/INSTALLATION.md) e [matriz de testes](docs/TEST_MATRIX.md).
