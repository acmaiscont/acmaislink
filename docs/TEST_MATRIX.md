# Matriz de testes do ACMAIS LINK

| Área | Cenário | Resultado esperado |
|---|---|---|
| Cadastro | Duas empresas com o mesmo nome e códigos diferentes | Ambas aparecem com código e nome |
| Cadastro | Código já utilizado | Operação recusada com mensagem clara |
| Segurança | Inspecionar `companies.json` | Nenhuma senha ou campo de senha |
| Segurança | URL HTTP ou fora de `sharepoint.com` | Operação recusada |
| Segurança | Inspecionar logs após acesso | Nenhuma senha ou conteúdo de documento |
| Acesso | Link compartilhado protegido por senha | Preenchimento e abertura da pasta |
| Acesso | Página atual usa `input#btnSubmitPassword` para “Verificar” | Controle é reconhecido e acionado pelo fluxo oculto |
| Acesso | Abrir uma empresa cadastrada | A mesma janela exibe a pasta, sem criar outra janela |
| Acesso | Autenticação e redirecionamento demorados | A janela permanece visível com feedback durante toda a transição |
| Cadastro | Informar somente link e senha | Código e nome são extraídos da pasta `código - nome` |
| Interface | Transição pela tela protegida | Página de senha permanece oculta ao usuário |
| Interface | Cancelar ou fechar cadastro/edição com campos vazios | Modal fecha sem acionar validação obrigatória |
| Interface | Abrir documentos | Botão e tela informam que a conexão está em andamento |
| Inicialização | Ponte do WebView ainda indisponível | Interface tenta reconectar e nunca fica presa em `Carregando...` |
| Navegação | Página do SharePoint renderiza senha de forma assíncrona | Aplicativo aguarda, autentica oculto e não retorna indevidamente ao início |
| Navegação | Evento de página carregada e temporizador se sobrepõem | Apenas uma verificação conclui; cobertura não reaparece após a pasta pronta |
| Navegação | Resposta antiga chega após cancelar e iniciar outro acesso | Não cancela, não cobre e não salva a operação nova |
| Cadastro | Cofre de credenciais demora enquanto o usuário cancela | Cancelamento responde; escrita tardia é revertida |
| Acesso | Campo de senha existe, mas botão de envio ainda não está pronto | Aguarda o botão do SharePoint sem clicar no cancelamento do app |
| Acesso | Campo de senha oculto permanece no DOM da pasta | Não inicia outra autenticação |
| Cadastro | Nome aparece em breadcrumb ou parâmetro `RootFolder` | Identificação extraída sem preenchimento manual |
| Sessão | Fechar e reabrir o aplicativo | Cookies persistem quando permitidos pelo SharePoint |
| Sessão | Executar o aplicativo novamente enquanto já está aberto | A segunda cópia encerra e a janela existente é restaurada em primeiro plano |
| SharePoint | Upload e download | Operações concluídas no WebView |
| SharePoint | Criar, renomear, mover e excluir pasta | Comportamento segue as permissões do SharePoint |
| Erro | Sem internet | Mensagem do WebView e fallback disponível |
| Erro | Senha ausente ou inválida | Mensagem compreensível e possibilidade de editar |
| Fallback | Abrir no navegador | URL correta aberta no navegador padrão |
| Atualização | Substituir executável | Configurações e credenciais preservadas |
| Atualização | Arquivos locais após troca de versão | CSS e JavaScript usam versão na URL para invalidar cache antigo |
| Recursos | Aplicação ociosa e navegando | Consumo compatível com WebView2 |

## Validação inicial realizada

Em 4 de setembro de 2026, o link de exemplo abriu a validação de senha do SharePoint e direcionou corretamente para `0000 - Teste`. A pasta exibiu o diretório `2026`. Upload, download, criação, renomeação, movimentação e exclusão não foram executados para evitar modificar o ambiente de exemplo.

## Regressão do carregamento — 17/09/2026

A suíte Python foi ampliada para reproduzir verificações concorrentes,
respostas obsoletas, cancelamento durante acesso ao cofre e falha na montagem
dos controles da pasta. A conclusão do cadastro e a troca de estado são
confirmadas juntas; cancelar não depende do JavaScript da página remota.

Os scripts injetados também têm testes de DOM em navegador real:

```powershell
node scripts/test-sharepoint-dom.cjs --report
```

Requer Node.js, Playwright disponível no caminho de módulos (`NODE_PATH`, se
externo), ambiente Python do projeto e Microsoft Edge no Windows. O script não
instala componentes. Há opções `ACMAIS_PYTHON` e `ACMAIS_BROWSER` para caminhos
alternativos. Todas as requisições são interceptadas: páginas e credenciais são
fictícias, sem acesso aos documentos dos clientes. Resultados locais ficam em
`.qa/sharepoint-dom/`, fora do repositório.

Esses testes não substituem a homologação da nova edição instalada com o link
real do cliente nem o teste de atualização entre duas Releases.

### Leitura nativa do WebView2 — revisão complementar de 17/09

- 103 testes Python e 23 cenários de DOM aprovados (revalidação em 18/09).
- Regressões adicionais: ponte JavaScript ausente, tarefa nativa sem resposta,
  descarte de ação expirada/cancelada, cobertura antes de navegar, início das
  consultas sem `loaded`, controles nativos após sucesso e autenticação sem
  recarregar o link.
- Cancelamento no intervalo entre enfileirar e executar a navegação: a URL
  antiga não pode substituir a home nem uma operação mais recente. A guarda
  também protege o retorno por erro e é conferida na thread da janela.
- No teste real do link de exemplo, o fluxo anterior retornou snapshots vazios
  durante a transição mesmo com navegação em andamento. O novo fluxo concluiu
  cadastro e reabertura com leitura direta do WebView2 e senha no cofre Windows.
- Os testes reais usam perfil e nome de serviço de credenciais exclusivos de QA;
  nenhuma empresa da instalação em uso é alterada. As credenciais temporárias
  são removidas ao encerrar o teste.
- Nenhum documento foi enviado, alterado, excluído ou baixado.

### Fluxo e seletor — 18/09/2026

- Regressões Python cobrem confirmação positiva da pintura antes de disco/cofre,
  eventos `loaded` durante preparação, cancelamento/timeout durante leitura,
  bloqueio de cliques concorrentes e descarte do documento da empresa anterior.
- `node scripts/test-opening-flow.cjs --report`: 13 cenários no Edge com rede
  interceptada; abertura/cadastro/edição usam “Abrindo documentos”, aguardam dois
  quadros, permitem cancelar antes da chamada e recuperam falhas do backend.
- `node scripts/test-sharepoint-dom.cjs --report`: 37 cenários, incluindo
  breadcrumbs semânticos, atributos de títulos e códigos numéricos sem espaços.
- O link real de uma empresa usa o padrão `150-NOME DA EMPRESA`, sem espaços
  ao redor do hífen; não foi enviada senha a esse link. O nome sem espaços foi
  reproduzido em regressão de extração e de persistência. A autenticação real da
  empresa 150 continua pendente por usar uma senha diferente.
- O marcador do nome na página de senha não é promovido a comprovação de pasta
  aberta. Nenhum teste modifica documentos do SharePoint.

### Revalidação do candidato — 13/10/2026

- 134 testes Python, 37 de DOM SharePoint e 13 do fluxo local aprovados.
- Ao abrir cadastro existente, uma pasta de outra empresa não é aceita apenas
  por estar no mesmo tenant. A identificação deve corresponder ao código
  selecionado; subpastas numeradas podem usar o ancestral da própria empresa.
- O executável isolado concluiu cadastro, persistência da senha no cofre e
  reabertura do link de exemplo. Os módulos de navegação compilados de QA e da
  distribuição foram comparados e são idênticos.
- Inspeção com controle de interface: barra compacta acima do SharePoint e
  lista do seletor nativo renderizadas corretamente. A instalação em uso não
  foi alterada. O acesso autenticado da empresa 150 ainda requer homologação.
- Clique real em “Abrir documentos”: feedback exibido, pasta aberta e cobertura
  removida. Selecionar a empresa já aberta não reiniciou a navegação; retorno à
  lista manteve o cadastro. Pacotes completos e de atualização gerados em
  `artifacts/validacao-2026-10-13-fluxo/`, com SHA-256 conferido.
