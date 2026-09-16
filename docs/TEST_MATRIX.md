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
