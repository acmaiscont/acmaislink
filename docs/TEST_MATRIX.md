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
