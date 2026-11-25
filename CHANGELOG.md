# Alterações

## 1.1.2

- Um único instalador para a primeira instalação e as atualizações.
- O instalador procura o WebView2 no Registro e, quando necessário, baixa o runtime pelo bootstrapper oficial da Microsoft. Essa instalação requer internet.
- O download para o site usa o nome `Instalar-ACMAIS-LINK.exe`.

## 1.1.1

- Cadastro de várias empresas a partir de um link e uma senha de grupo no SharePoint.
- Abertura e envio direcionados à pasta da empresa selecionada, com preservação dos cadastros individuais existentes.

## 1.1.0

- Envio guiado para o SharePoint por empresa, setor, tipo de documento e competência. Os atalhos preenchem o mês atual ou anterior.
- Envio de arquivos avulsos ou pastas inteiras, com criação da estrutura de destino e progresso por item.
- Sugestões de destino para notas fiscais, extratos e documentos contábeis reconhecidos.
- Histórico local por item e resultado com motivos de falha, inclusive identificação de nomes duplicados com preservação dos arquivos existentes.
- Reabertura em janela única, com confirmação quando houver uma operação em andamento. A tela inicial é carregada diretamente do pacote.

## 1.0.0

- Atualizações automáticas e silenciosas pelo GitHub Releases, com digest SHA-256 obrigatório.
- Dois instaladores x64: completo offline com WebView2 e leve para atualização.
- Comandos nativos privilegiados protegidos por capacidade da interface local.
- Bloqueio de envio da senha para outro tenant SharePoint e validação rigorosa de URL.
- Identificação da empresa renderizada como texto para impedir injeção HTML.
- Cadastro duplicado recusado antes de alterar credenciais.
- Prazo de abertura independente de eventos de carregamento e botão de cancelar.
- Confirmação de exclusão reinicializada; erros de operação exibidos ao usuário.
- Tela inicial mais compacta, foco visível e suporte a movimento reduzido.
- Janela única preservada; tentativa de segunda instância restaura a existente.
- Refinamento da mesma 1.0.0: tamanho inicial ajustado à área útil e à escala do Windows.
- Interface responsiva, cartões flexíveis e formulários com ações fora da área de rolagem.
- Erros de cadastro dentro do formulário; falha de carregamento com opção de tentar novamente.
- Busca ignora acentos, informa resultados filtrados e aceita Ctrl+F; abertura pode ser cancelada por Escape.
- Reinstalação da mesma versão com preparação em staging e cópia de segurança da edição anterior.
- Aviso sem WebView2 identifica o instalador completo e oferece abrir os downloads oficiais.
- Consulta automática ao abrir e a cada 4 horas; download em segundo plano sem confirmação.
- Instalação silenciosa somente após fechar a janela; documentos em uso não são interrompidos.
- Cache de atualização reconfirmado com o GitHub em cada sessão e revalidado antes de executar.
- Rodapé apenas informativo, sem botões de atualização nem perguntas ao usuário.
- Nova abertura aguarda por até 30 segundos se a troca de arquivos estiver em andamento.
- Correção da cobertura de carregamento que reaparecia após abrir a pasta: verificações de navegação serializadas e respostas antigas descartadas.
- Cancelamento e prazo de abertura continuam disponíveis durante operações lentas de credenciais; cadastro cancelado não é concluído depois.
- Autenticação aguarda o botão correto do SharePoint, sem acionar os controles do aplicativo; campos de senha ocultos são ignorados.
- Identificação da empresa também reconhece breadcrumbs e URLs com `RootFolder`.
