# Instalação do ACMAIS LINK

## Desenvolvimento no Windows

1. Instale Python 3.11 ou superior.
2. Confirme que o Microsoft Edge WebView2 Runtime está disponível.
3. Abra o PowerShell na pasta do projeto.
4. Execute `scripts\setup.ps1`.
5. Execute `scripts\run.ps1`.

O uso normal não requer privilégios administrativos.

## Distribuição

Execute `scripts\build.ps1` e `scripts\package.ps1` após preparar as ferramentas.
Os instaladores `full` e `update` ficam em `artifacts`. O completo inclui WebView2
offline; o leve exige o runtime existente. Ambos instalam por usuário e criam
atalhos. Consulte [lançamento](RELEASE.md) para validações e aprovação pendentes.

## Atualização

O aplicativo instalado procura e baixa versões estáveis superiores em segundo
plano, sem perguntas. A atualização pronta é aplicada silenciosamente quando o
usuário fecha a janela, preservando os arquivos da versão anterior. Na próxima
abertura pelos atalhos, a versão nova será utilizada. Falhas de rede ou integridade
não interrompem o uso; uma nova tentativa será feita depois.

Instale esta edição 1.0.0 uma vez para habilitar esse comportamento. Cópias avulsas
e execução pelo código-fonte não atualizam a instalação do usuário.
O perfil em `%APPDATA%\ACMAIS\ACMAIS LINK`
contém links compartilhados e sessão local; proteja esse diretório. As senhas
permanecem no cofre do Windows.
