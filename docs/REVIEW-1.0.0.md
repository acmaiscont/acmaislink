# Revisão do candidato 1.0.0

Revisado em 9–15/09/2026. Candidato local para aprovação; nenhum push, tag ou
Release foi publicado. Repositório público confirmado: acmaiscont/acmaislink.

## Correções e proteções

- Capacidade aleatória protege os comandos privilegiados da ponte nativa. O
  documento remoto não recebe o token da interface local.
- A senha só é enviada ao mesmo hostname SharePoint selecionado; a origem é
  conferida novamente dentro do JavaScript imediatamente antes do preenchimento.
- URLs com porta inesperada, credenciais, caracteres de controle ou sintaxe
  inválida são rejeitadas. Nome da empresa é texto, sem interpretação de HTML.
- Cadastro duplicado não substitui senha existente. Falha ao salvar configuração
  restaura a senha anterior; uma conclusão atrasada não salva um cadastro cancelado.
- Prazo independente de eventos de carregamento evita espera sem retorno quando
  o servidor não responde. Há cancelamento na interface local e na cobertura remota.
- Exclusão reinicializa a confirmação, evitando reutilizar uma decisão anterior.
- Consulta de atualização tem feedback e não bloqueia o restante da interface.
- Download exige versão estável superior, asset leve do repositório correto,
  tamanho esperado e SHA-256 do GitHub. Conteúdo corrompido é descartado.
- Instalador verifica WebView2, bloqueia atualização com o app aberto, preserva
  versões anteriores e não remove os cadastros ao desinstalar.

## Evidências de validação

| Verificação | Resultado |
| --- | --- |
| Suíte Python | 27 testes aprovados após reconciliação das fontes |
| Auditoria pip-audit | Sem vulnerabilidades conhecidas nas dependências auditadas em 09/09 |
| JavaScript local e scripts gerados | Sintaxe validada com Node |
| UI real Windows | Tela inicial carregou; cadastro cancelou com campos vazios; consulta exibiu ausência de Release |
| Executável empacotado | Abriu e carregou os controles da versão 1.0.0 |
| Instalador leve com app aberto | Retornou código 2 sem instalar |
| Instalador leve com app fechado | Retornou código 0; hash do executável instalado igual ao compilado |
| Segunda execução instalada | Encerrou com código 0; permaneceu apenas uma instância |
| Registro de desinstalação | Versão 1.0.0 e caminho entre aspas conferidos |
| WebView2 completo | Instalador offline incluído; assinatura Microsoft válida |

A tabela acima registra a validação do candidato anterior. A edição refinada,
também 1.0.0, foi recompilada e empacotada em 11/09, com a conferência abaixo.

## Refinamento de interface da mesma 1.0.0

- Janela inicial limitada à área útil do monitor primário e à escala do Windows,
  incluindo espaço ocupado pela barra de tarefas. Mínimo reduzido e limitado
  também em telas pequenas; fallback maximizado se a consulta do monitor falhar.
- Cabeçalho e rodapé compactos; conteúdo central rolável; cartões flexíveis e
  nomes/códigos longos sem transbordamento horizontal.
- Formulários com conteúdo rolável e ações sempre fora da área de rolagem.
  Cancelar, fechar e Escape não exigem preencher campos obrigatórios.
- Erros de cadastro dentro do diálogo; falha de carregamento persistente com
  tentativa manual; busca ignora acentos, indica quantidade filtrada e aceita Ctrl+F.
- Cancelamento por Escape e proteção contra respostas de abertura/cadastro
  atrasadas. Foco permanece na cobertura de abertura enquanto ela estiver ativa.
- Aviso sem WebView2 identifica o pacote completo. Reinstalação da mesma versão
  prepara arquivos antes da troca e preserva a edição anterior em backup.

| Validação da edição refinada | Resultado |
| --- | --- |
| Suíte Python em 11/09 | 33 testes aprovados, incluindo 6 de geometria/DPI |
| Interface com API simulada | 8 perfis aprovados: 360×640, 640×360, 820×580, 1024×600, 1366×768, equivalente a zoom 200%, 480×290 e 320×240 |
| Interações adicionais | Recuperação de listagem, busca sem acentos, teclado, foco e resposta atrasada após cancelar aprovados |
| JavaScript no navegador de teste | Nenhum erro não tratado nos cenários executados |
| Executável real em 15/09 | Abriu, carregou lista vazia, cancelou cadastro vazio e exibiu layout maximizado |
| Instalador refinado com app aberto em 15/09 | Retornou código 2, sem substituir instalação |
| Consistência de fontes/executável em 15/09 | Manifesto confere, sem necessidade de nova compilação |
| Integridade dos dois instaladores em 15/09 | SHA-256 confere com SHA256SUMS.txt |
| Reinstalação real da edição refinada | Pendente: proteção do ambiente recusou substituir a instalação atual sem autorização explícita |

As evidências de layout e interações estão em `.qa/ui-responsive-20260911/`
(JSON com hashes das fontes, harness e 48 capturas). A matriz usa Edge headless
isolado e respostas nativas simuladas; não substitui testes reais do SharePoint.
A conferência visual nativa usou perfil de teste isolado, sem alterar cadastros.
As tentativas de reduzir a janela pelo controle remoto não confirmaram uma
dimensão menor; a cobertura de telas pequenas é a matriz automatizada acima.

Por manter a versão 1.0.0, a edição refinada precisa ser aplicada manualmente
pelo instalador; o mecanismo de atualização só instala versões superiores.
Não limpar cache nem apagar cadastros como requisito para aplicar esta edição.
Detalhes e limites da troca estão em [INSTALLER-REFINEMENT.md](INSTALLER-REFINEMENT.md).

A instalação de teste foi feita no contexto local do host Codex. O caminho de
instalação/perfil pode sofrer redirecionamento do Windows nesse contexto; isso
não substitui o teste de instalação por um usuário em uma máquina limpa.

## Atualização automática e silenciosa — 15/09/2026

Esta etapa substitui os controles manuais de atualização das revisões anteriores,
sem mudar a versão 1.0.0. O aplicativo instalado consulta o GitHub ao mostrar a
janela e a cada 4 horas, baixa o pacote leve em segundo plano e o aplica com `/S`
apenas depois do fechamento normal. Não pede confirmação, não encerra a janela
para instalar e não reabre o aplicativo após a instalação. A interface exibe só
um estado discreto e não possui comando para instalar.

O cache local precisa ser reconfirmado pelo GitHub em cada sessão; metadados e
bytes adulterados, caminhos externos e versões iguais/inferiores não são
executados. O fechamento não espera pela rede. Apenas um pacote que já estava
pronto naquele momento pode ser iniciado. A nova abertura aguarda por tempo
limitado se a trava da instalação ainda estiver ativa.

- 65 testes Python aprovados, incluindo controlador, cache, integridade,
  lançamento com `/S`, ordem fechamento → liberação da trava → instalação e
  reabertura concorrente. Os lançamentos de instalador nesses testes são simulados.
- 8 perfis de interface aprovados novamente em 15/09, inclusive 200% e 320×240.
- Estados de atualização, falha de rede e timeout sem toast, modal, pergunta ou
  mudança de foco; consulta de estado somente na home local autorizada.
- Evidências em `.qa/ui-responsive-20260915/`: quatro relatórios JSON e 49 capturas.
- Executável recompilado e dois instaladores regenerados em 15/09; fontes da
  matriz de UI correspondem aos hashes do build. Consulta real pelo UpdateService
  retornou `ok=true, available=false`, sem Release pública disponível.
- Nenhum instalador foi aplicado à instalação real nesta etapa. Uma instância
  instalada estava aberta e foi preservada. A validação real entre duas Releases
  permanece pendente antes da distribuição ampla.

Esta edição deve ser instalada uma vez para habilitar o fluxo automático.
Execuções por código-fonte ou por cópias avulsas não alteram a instalação.
As proteções e possíveis avisos do Windows não são desativados; a assinatura de
código continua como pendência para distribuição.

## Conflito de sincronização identificado

Na retomada em 10/09, 18 arquivos principais tinham voltado à versão anterior,
enquanto as alterações de 09/09 estavam em cópias `-COMP16`. As fontes foram
reconciliadas e 25 cópias, incluindo caches, preservadas em
`.qa/onedrive-conflicts-20260910/`. Nenhuma cópia foi apagada.

O processo de build agora verifica versões e cópias de conflito, registra hashes
das fontes e do executável e recusa empacotar arquivos alterados após a compilação.
Uma alteração simulada na impressão digital das fontes foi recusada em teste.
Diretórios de saída marcados como somente leitura pelo OneDrive também impediram
a reconstrução; o build agora trata esse atributo apenas na sua própria saída.
Isso detecta divergência; não impede o OneDrive de substituir arquivos. Para a
publicação, preferir o workflow GitHub Actions em ambiente isolado da sincronização.

## Pendências antes de distribuição ampla

- Aprovação do proprietário sobre este candidato e suas alterações.
- Instalação do pacote completo em VM Windows x64 sem WebView2.
- Atualização real entre duas Releases controladas. O repositório ainda não
  possui uma Release pública, portanto a validação de download foi feita com
  respostas e arquivos controlados, além da consulta real ao GitHub.
- Definir assinatura de código Windows. Os instaladores ACMAIS não são assinados.
- Executar o workflow no GitHub após autorização para enviar o código.

Os pacotes e seus hashes ficam em `artifacts/`. O procedimento de publicação
está em [RELEASE.md](RELEASE.md). A revisão reduz riscos conhecidos; não representa
garantia de ausência de falhas nem teste exaustivo de todos os fluxos SharePoint.

## Referências

- [Distribuição do WebView2 — Microsoft](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution)
- [GitHub Releases API](https://docs.github.com/en/rest/releases/releases#get-the-latest-release)
- [Projeto de referência fornecido](https://github.com/bezumiya/GoLiveBypass)

O mecanismo ACMAIS foi implementado para Python/pywebview, sem copiar o código
do projeto de referência.
