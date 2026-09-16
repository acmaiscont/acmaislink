# Configuração do ACMAIS LINK

## Cadastrar uma empresa

1. Selecione **Adicionar empresa**.
2. Informe o link compartilhado HTTPS do SharePoint e a senha.
3. Selecione **Validar e abrir**. Código e nome são extraídos da pasta no padrão `código - nome da empresa`.

Empresas com nomes iguais são permitidas; códigos repetidos não são.

## Alterar uma empresa

Use **Editar** no cartão. Deixe a senha vazia para preservar a credencial atual.
A identificação é confirmada novamente pelo link. Se o código da pasta mudar,
a aplicação migra o cadastro e a credencial. Cancelar não exige preencher campos.

## Backup

Feche o aplicativo e copie `%APPDATA%\ACMAIS\ACMAIS LINK\companies.json`. Esse arquivo contém somente código, nome e URL. As senhas não fazem parte do backup e devem ser cadastradas novamente em outro computador.

## Diagnóstico

Os logs ficam em `%APPDATA%\ACMAIS\ACMAIS LINK\logs`. Eles registram eventos e falhas por código de empresa, sem senha nem conteúdo de documentos.
