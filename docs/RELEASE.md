# Distribuição do ACMAIS LINK

O repositório de distribuição é https://github.com/acmaiscont/acmaislink.
O aplicativo consulta apenas Releases públicas estáveis.
A versão pública atual é a [1.1.3](https://github.com/acmaiscont/acmaislink/releases/tag/v1.1.3).
A atualização pública da 1.1.2 é diretamente para a 1.1.3. Os instaladores de
homologação com perfil separado não fazem parte da distribuição.

## Pacotes

| Arquivo | Uso |
| --- | --- |
| ACMAIS-LINK-<versão>-x64-update.exe | Instalador único para primeira instalação e atualização. |
| Instalar-ACMAIS-LINK.exe | Mesmo instalador com o nome mostrado no download do site. |
| ACMAIS-LINK-x64-update.exe | Cópia para o endereço de download já divulgado. |

O instalador usa o bootstrapper da Microsoft quando o WebView2 está ausente.
Essa etapa precisa de internet.

Windows 10/11 x64. Instalação por usuário em `%LOCALAPPDATA%\Programs\ACMAIS LINK`.
Atalhos na área de trabalho e menu Iniciar. Na instalação manual, o assistente
pede para fechar o app antes de copiar arquivos. Atualizações automáticas não
abrem assistente e só são aplicadas depois de o usuário fechar a janela.
Cada versão fica em `versions\<versão>`; versões
anteriores não são apagadas. Para voltar, feche o aplicativo e abra o executável
da versão anterior. Configuração e credenciais permanecem fora da instalação.
Desinstalar preserva cadastros, senhas e WebView2.

## Atualizações

O aplicativo instalado consulta `/repos/acmaiscont/acmaislink/releases/latest`
em segundo plano depois de mostrar a janela e repete a consulta a cada 4 horas.
Uma versão estável superior é baixada automaticamente, sem pedir confirmação.
O rodapé é somente informativo, sem botões de consulta ou instalação.

Quando o usuário fecha a janela normalmente, o aplicativo libera a trava de
instância única e executa o pacote verificado com `/S`. Não encerra documentos
em uso, não mostra assistente e não reabre a janela depois da instalação. A
próxima abertura pelos atalhos usa a nova versão. Se outra instância reabrir
antes da troca, o instalador adia a operação com segurança. Se o instalador já
estiver trocando os arquivos, uma nova abertura aguarda por até 30 segundos.

O download é limitado a 250 MiB/5 minutos, exige tamanho exato e digest SHA-256
fornecido pelo GitHub. Origem e redirecionamentos HTTPS são restritos.
O instalador só é executado depois da validação. Sem rede, sem release, pacote
incompleto ou hash incorreto: a instalação existente permanece utilizável.
Falhas ficam no log, sem perguntas ao usuário, e a consulta é repetida depois.

O cache em `%APPDATA%\ACMAIS\ACMAIS LINK\updates` evita repetir um download
concluído. O manifesto local não é prova de autenticidade: o GitHub precisa
confirmar seus metadados nesta sessão antes de liberar a execução. Os bytes
são conferidos novamente no fechamento. Um download ainda incompleto ao fechar
não bloqueia a saída e não será instalado naquela sessão. Cache e versões
anteriores podem ocupar espaço adicional; não há remoção automática de versões.

Execuções por código-fonte e cópias avulsas de desenvolvimento não aplicam
atualizações. Apenas o executável empacotado na instalação padrão, com o marcador
de instalação concluída, habilita esse fluxo. Próximas Releases precisam
ter versão superior à instalada.

O hash detecta corrupção e troca de bytes; não protege contra comprometimento
do próprio repositório. Proteger conta e permissões de publicação do GitHub é
parte da segurança da distribuição. Não há token GitHub embutido. Para clientes
sem login, repositório e Releases precisam ser públicos.

## Construção

1. Python 3.12 x64; criar `.venv` e instalar `requirements-build.txt`.
2. `python -m pip install --no-deps -e .`
3. Executar `scripts/prepare-tools.ps1` (NSIS 3.12 com hash fixado; WebView2 com assinatura Microsoft validada).
4. Executar `scripts/build.ps1` e `scripts/package.ps1`.
5. Conferir que todos os nomes do instalador têm o mesmo hash em `artifacts/SHA256SUMS.txt`.

O workflow manual gera artefatos de revisão, sem publicar Releases.
O build registra `release-v<versão>/source-manifest.json` e o empacotamento exige
que fontes e arquivos compilados ainda correspondam aos hashes registrados.
Se o OneDrive produzir cópias de conflito, reconcilie-as antes de compilar.

## Após aprovação do proprietário

As instruções para atualizar o botão do site estão em
[`site-downloads/README.md`](../site-downloads/README.md).

1. Revisar código e documentos; enviar apenas arquivos versionados para `main`.
2. Validar o mesmo instalador em VMs Windows com e sem WebView2.
3. Testar atualização da versão pública anterior para a candidata em ambiente de teste:
   download sem prompts, uso de documentos preservado, aplicação silenciosa ao
   fechar e próxima abertura na nova versão. Não publicar uma Release de teste
   como estável no repositório de produção: todos os clientes instalados consultarão esse canal.
4. Definir assinatura de código Windows. Os EXEs ACMAIS atuais não são assinados;
   o Windows pode apresentar SmartScreen. O WebView2 incluído é assinado pela Microsoft.
5. Criar a tag da versão e a Release inicialmente em draft. Anexar o instalador
   versionado, `Instalar-ACMAIS-LINK.exe`, `ACMAIS-LINK-x64-update.exe` e
   `SHA256SUMS.txt`. No site, use o
   [link direto do instalador](https://github.com/acmaiscont/acmaislink/releases/latest/download/Instalar-ACMAIS-LINK.exe).
   Conferir hashes, notas e nomes antes de publicar como estável.
6. Nas próximas versões, manter exatamente `ACMAIS-LINK-<versão>-x64-update.exe`.
   O GitHub precisa fornecer `digest: sha256:...` no asset. Sem digest, o app recusa.

## Limites da validação local

Use uma máquina de teste ou VM sem o runtime e com acesso à internet para
validar a instalação real pelo bootstrapper. Confira também se a tela inicial
é renderizada. Os resultados do Windows Sandbox e do Windows fora do Sandbox
estão na [matriz de testes](TEST_MATRIX.md).

Referências: [modo silencioso NSIS](https://nsis.sourceforge.io/Docs/Chapter3.html)
e [ciclo de execução pywebview](https://pywebview.flowrl.com/guide/usage).
