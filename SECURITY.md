# Segurança

Senhas de links são armazenadas pelo keyring no cofre do Windows. Não gravar
senhas, tokens, links de clientes ou dados pessoais em issues, releases ou commits.
O arquivo companies.json contém links compartilhados e deve ser tratado como dado
confidencial, embora não contenha senhas. Cookies do WebView2 persistem no perfil.

A ponte nativa exige uma capacidade aleatória para cadastro, exclusão, listagem,
abertura arbitrária de empresa e consulta do estado de atualização. A capacidade só é entregue ao
documento inicial local. Páginas remotas têm somente comandos de retorno e abertura
externa da empresa atual. A senha só é enviada no mesmo hostname SharePoint do link
selecionado. Identificação remota é inserida como texto, não HTML.

Atualizações confiam na conta/repositório acmaiscont/acmaislink, TLS e digest do
asset GitHub. Assinar os executáveis é uma etapa recomendada para distribuição
ampla. Não há chave privada ou credencial de publicação no aplicativo.
O download é automático e a instalação só ocorre depois de a janela ser fechada
normalmente. Não há comando de instalação exposto à WebView. O manifesto do cache
não é confiável sozinho: origem, versão, tamanho e digest precisam ser confirmados
pelo GitHub nesta sessão, e o pacote é novamente verificado antes da execução.
Execuções avulsas/de desenvolvimento não alteram a instalação silenciosamente.

Relate falhas diretamente à equipe ACMAIS; não publique credenciais ou links de
clientes. A auditoria de dependências é pontual e não prova ausência de falhas.
