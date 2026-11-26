# Instalação do ACMAIS LINK

## Instalação para clientes

1. Em Windows 10 ou 11 de 64 bits, baixe o
   [instalador oficial](https://github.com/acmaiscont/acmaislink/releases/latest/download/Instalar-ACMAIS-LINK.exe).
2. Execute `Instalar-ACMAIS-LINK.exe` e abra o ACMAIS LINK pelo atalho instalado.

O mesmo instalador serve para primeira instalação e atualização manual.
Se o WebView2 Runtime estiver ausente, o instalador baixa o componente oficial
da Microsoft e tenta instalá-lo silenciosamente. Essa etapa exige internet.
Uma falha na instalação do componente interrompe a instalação do aplicativo.

## Desenvolvimento no Windows

1. Instale Python 3.11 ou superior.
2. Confirme que o Microsoft Edge WebView2 Runtime está disponível.
3. Abra o PowerShell na pasta do projeto.
4. Execute `scripts\setup.ps1`.
5. Execute `scripts\run.ps1`.

O uso normal não requer privilégios administrativos.

## Distribuição

Execute `scripts\build.ps1` e `scripts\package.ps1` após preparar as ferramentas.
O instalador fica em `artifacts`. A instalação verifica o
WebView2 no Registro do Windows para o computador e para o usuário atual. Caso
falte, o bootstrapper da Microsoft usa a internet para instalar o componente
silenciosamente. O mesmo pacote serve para primeira instalação e atualização,
instala o aplicativo por usuário e cria atalhos.

## Atualização no Windows

O aplicativo instalado procura e baixa versões estáveis superiores em segundo
plano, sem perguntas. A atualização pronta é aplicada silenciosamente quando o
usuário fecha a janela, preservando os arquivos da versão anterior. Na próxima
abertura pelos atalhos, a versão nova será utilizada. Falhas de rede ou integridade
não interrompem o uso; uma nova tentativa será feita depois.

O fluxo automático está disponível para quem usa o aplicativo instalado pelo
pacote oficial. Cópias avulsas e execução pelo código-fonte não atualizam a
instalação do usuário.
O perfil em `%APPDATA%\ACMAIS\ACMAIS LINK`
contém links compartilhados e sessão local; proteja esse diretório. As senhas
permanecem no cofre do Windows.

## Candidatos para macOS e Linux

Os pacotes de homologação ficam nos artefatos da execução do GitHub Actions.
A árvore de versões públicas continua distribuindo o instalador Windows.

- **macOS 15**. Use o ZIP correspondente ao processador (Apple Silicon ou
  Intel). O ZIP contém o aplicativo `ACMAIS LINK.app`, que usa o WKWebView e
  o Keychain do sistema. Candidatos de CI usam assinatura local de compilação.
  Para distribuição direta, assine com Developer ID, envie à notarização da
  Apple e valide o pacote baixado em um perfil limpo com o Gatekeeper ativo.
- **Ubuntu 24.04 x64**. Extraia o TAR.GZ e execute `ACMAIS LINK` dentro da
  pasta extraída. Mantenha a pasta `_internal` ao lado do executável. A sessão
  gráfica deve ter GTK 3, WebKitGTK 4.1 e um cofre Secret Service desbloqueado.
  No Ubuntu, instale as dependências com
  `sudo apt install gir1.2-gtk-3.0 gir1.2-webkit2-4.1 gnome-keyring`.

Para rodar pelo código-fonte no Ubuntu, instale também `python3-venv`,
`python3-gi` e `python3-gi-cairo` e use
`/usr/bin/python3 -m venv --system-site-packages .venv`. No macOS, use
`python3 -m venv .venv` com Python 3.12. Em ambos os sistemas:

```sh
.venv/bin/python -m pip install -r requirements-portable-build.txt
.venv/bin/python -m pip install -e .
.venv/bin/python launcher.py
```

O perfil fica em `~/Library/Application Support/ACMAIS/ACMAIS LINK` no macOS,
e em `${XDG_CONFIG_HOME:-~/.config}/acmais-link` no Linux. A primeira
portabilidade mantém uma instância por perfil e preserva a janela em execução
quando há uma segunda tentativa de abertura. As atualizações destes pacotes são
manuais. Substituir a pasta do aplicativo preserva os cadastros e o histórico do
mesmo usuário. As senhas permanecem no cofre do sistema.

## Empresas de um grupo

Desde a versão 1.1.3, ao abrir os documentos de uma empresa de grupo, o app
consulta o SharePoint em segundo plano e adiciona à lista as novas pastas no
padrão `código - nome da empresa`.
O botão **Atualizar grupo**, no cartão de qualquer empresa do grupo, consulta a
pasta imediatamente e informa o resultado. Ambas as opções usam o link e a
senha já salvos. Cadastros existentes e empresas removidas manualmente após
esta atualização mantêm seu estado.

## Produção e Piloto

O Piloto usa sua própria instalação e seu próprio perfil em
`%APPDATA%\ACMAIS\ACMAIS LINK Piloto`. A desinstalação remove o aplicativo e o
atalho do canal selecionado e preserva o perfil local, inclusive cadastros e
histórico. O WebView2 Runtime é compartilhado e permanece instalado.
