# Refinamento do instalador 1.0.0

Os pacotes continuam com a versão **1.0.0**. O pacote `update` atende tanto a uma
instalação inicial em um computador com WebView2 quanto à reinstalação desta
edição. O pacote `full` inclui o instalador offline do WebView2 e também pode
reinstalar a mesma versão. Os nomes dos dois arquivos permanecem iguais.

Quando o WebView2 está ausente, o pacote leve informa o nome completo do pacote
`full` e oferece abrir a página oficial de Releases. No modo silencioso, termina
com código 3, sem abrir navegador nem bloquear esperando resposta. A página de
Releases só disponibilizará os downloads após a publicação aprovada.

## Reinstalação e preservação

O marcador `.complete` já não impede reinstalar a versão. A instalação segue
esta ordem:

1. Verifica os requisitos e aguarda o fechamento do aplicativo.
2. Reserva o controle de instância única para impedir uma abertura durante a troca.
3. Extrai todos os arquivos em uma pasta exclusiva de preparação.
4. Renomeia a pasta anterior `versions\1.0.0`, quando presente, para um backup
   exclusivo `versions\.previous-1.0.0-<processo>-<contador>`.
5. Promove a pasta preparada para `versions\1.0.0` e atualiza os atalhos.

Se a extração falhar, a pasta instalada permanece intacta. Se a promoção falhar
após criar o backup, o instalador tenta restaurar o nome original e informa o
caminho de recuperação caso a restauração também seja impedida pelo Windows.
As pastas de backup não são removidas durante uma instalação. Pastas de
preparação deixadas por uma falha também são preservadas para diagnóstico; por
isso uma reinstalação requer espaço livre para uma cópia adicional do programa.

O instalador usa uma trava separada para evitar assistentes concorrentes. Os
dados de empresas em `%APPDATA%\ACMAIS\ACMAIS LINK`, as credenciais do Windows e
o WebView2 permanecem fora dessas trocas. A instalação é por usuário na pasta
padrão `%LOCALAPPDATA%\Programs\ACMAIS LINK`; substituição via `/D` é rejeitada
para manter o mesmo limite de diretório exigido pelo desinstalador.

## Validação antes de distribuir

- Compilar ambos os pacotes com `scripts\package.ps1` após o build do aplicativo.
- Instalar sobre a edição 1.0.0 anterior com o aplicativo fechado: conferir a
  interface refinada, o backup, os atalhos e a manutenção dos cadastros.
- Repetir com o aplicativo aberto: o instalador deve aguardar fechamento; cancelar
  deve manter a edição existente utilizável.
- Abrir um segundo instalador enquanto o primeiro está aberto: deve informar que
  já há uma instalação em andamento.
- Em Windows de teste sem WebView2: conferir o aviso e o link do pacote leve,
  depois instalar com o pacote completo. Em modo `/S`, o leve deve sair com código 3.
- Em um perfil descartável, bloquear a renomeação da pasta instalada e verificar
  que a instalação falha preservando a edição anterior.

A troca por renomeação reduz o risco de uma instalação parcial, mas não constitui
uma transação de disco: encerramento forçado do processo ou queda de energia
entre as renomeações pode exigir restaurar a pasta de backup. O instalador não
apaga esse backup e a reinstalação pode ser executada novamente.

O mecanismo automático de atualização continua comparando versões: uma edição
refinada com o mesmo número precisa ser reinstalada manualmente. Nenhuma Release
é publicada por essas alterações.
