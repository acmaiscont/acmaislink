# Arquitetura do ACMAIS LINK

## Decisão técnica

O MVP usa Python 3.11 ou superior, pywebview e keyring. A combinação utiliza o WebView2 no Windows, mantém a interface em HTML e CSS e delega credenciais ao cofre nativo. Electron foi descartado no MVP pelo tamanho e consumo; C# com WPF não atende ao objetivo multiplataforma; Tauri é uma alternativa futura caso a equipe adote Rust e necessite de uma distribuição ainda mais compacta.

## Componentes

- `models.py`: valida e representa empresas. Somente URLs HTTPS de subdomínios `sharepoint.com` são aceitas.
- `config_store.py`: persiste código, nome e URL de forma atômica em `companies.json`.
- `credential_store.py`: acessa Windows Credential Manager, Keychain ou keyring equivalente.
- `api.py`: coordena a janela única, a máquina de estados de navegação e o fallback para navegador. Objetos nativos e dependências permanecem privados para não serem serializados pela ponte JavaScript.
- `navigation_window.py`: no Windows, executa leituras de DOM diretamente pelo WebView2, com limite de três segundos por tentativa. A cobertura e a barra de navegação são controles da própria janela, independentes da ponte JavaScript e do carregamento do SharePoint.
- `sharepoint.py`: gera a automação restrita à página de senha do link compartilhado.
- `web/`: interface local de seleção e manutenção de empresas.
- `bridge.py`: capacidade aleatória para comandos privilegiados, entregue somente ao documento local inicial.
- `updater.py`: consulta de Releases estáveis, download HTTPS limitado e digest SHA-256 obrigatório.
- `auto_update.py`: consulta periódica em thread daemon, cache reconfirmado nesta sessão e instalação silenciosa somente após fechar a janela normalmente. A interface apenas consulta o estado; não pode iniciar instalações.
- `runtime.py`: detecção de WebView2 no registro antes de criar a janela.
- `installer/`: dois instaladores NSIS, com ou sem WebView2, usando diretórios por versão.

## Fluxo de acesso

1. A interface recebe somente o link e a senha no cadastro.
2. A interface aguarda dois quadros de pintura antes de chamar o backend. No Windows, a etapa `preparing` confirma a pintura da cobertura nativa antes de consultar disco/cofre e carregar o endereço. Eventos `loaded` não inspecionam documentos nessa etapa. A janela nunca é ocultada e o cancelamento não depende do SharePoint.
3. Após o redirecionamento, o código e o nome são extraídos da pasta `código - nome da empresa`. Códigos numéricos também aceitam hífen sem espaços (`150-Empresa`); espaços repetidos/quebras são normalizados. A extração usa caminhos explícitos e títulos/breadcrumbs, nunca texto indiscriminado da página de senha.
4. A identificação e o link compartilhado são armazenados separadamente da credencial.
5. A navegação aguarda a renderização assíncrona da página protegida; a mesma janela mostra a pasta, com barra compacta para retornar, selecionar outra empresa ou abrir no navegador. Seleções programáticas/obsoletas não iniciam acesso.
6. O SharePoint controla sessão, cookies, upload, download e operações de documentos.

As verificações começam junto com a navegação, sem depender de `loaded` ou da
injeção de `window.pywebview` na página remota. Leituras sem resposta são
repetidas dentro do prazo global de 60 segundos. O envio da senha confere o
domínio, a URL exata do documento e a operação atual; não é repetido por uma
resposta antiga. Reautenticar uma página já aberta não recarrega o link.

Uma trava nomeada do Windows garante instância única. Uma segunda execução restaura e ativa a janela já existente, sem criar outra WebView.
Durante a troca silenciosa de arquivos, a nova execução aguarda a trava por tempo
limitado. O controlador automático é habilitado apenas na instalação padrão,
nunca em cópias avulsas de desenvolvimento.

## Segurança

A senha não aparece em JSON, argumentos de linha de comando ou logs. A aplicação rejeita HTTP, domínios externos e URLs com credenciais embutidas. O armazenamento persistente da sessão fica no diretório de dados do usuário e é separado do executável.
