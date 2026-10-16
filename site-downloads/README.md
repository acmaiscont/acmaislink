# Página de downloads ACMAIS

Página estática para o site existente, sem dependências, login, cookies,
analytics ou coleta de dados. O único programa disponibilizado é o ACMAIS LINK.

## Publicação no site atual

1. Faça um backup da pasta `/downloads/`, caso já exista na hospedagem.
2. Copie **o conteúdo de `dist/`**, preservando as subpastas, para `/downloads/`.
3. Adicione no menu do site um link para `https://acmaiscont.com.br/downloads/`.
4. Confirme a página por HTTPS e teste os dois botões de download.

Os instaladores são entregues pelo GitHub Releases. Não é necessário copiá-los
para a hospedagem nem dar login GitHub ao cliente. Não substitua a página inicial,
o backend ou a configuração de DNS. Os assets são relativos, permitindo servir
o mesmo conteúdo em outra subpasta. Hospedagens com CMS podem exigir que a equipe
responsável crie a rota estática equivalente; não cole o HTML inteiro num editor
visual que remova seus estilos.

## Prévia local

Na raiz do repositório:

```powershell
python -m http.server 8768 --bind 127.0.0.1 --directory site-downloads/dist
```

Abra `http://127.0.0.1:8768/`. Não precisa de Node.js ou compilação para publicar.

## Manutenção

- `dist/index.html`: textos, versão, tamanhos e links dos pacotes.
- Os downloads apontam para a versão estável `v1.0.0`, não para arquivos locais.
- Ao lançar outra versão, atualize os dois links, a versão, os tamanhos e as
  notas em conjunto. Confira os hashes no arquivo `SHA256SUMS.txt` da Release.
- Adicione outros programas somente após autorização de distribuição ao cliente.
- Não inclua links ou senhas de pastas de clientes no HTML, no Git ou no pacote.

## Validação e rollback

Conferir 320, 375, 768 e 1440 pixels; navegação por teclado; FAQ sem JavaScript;
ausência de rolagem horizontal; URLs públicas dos arquivos; caracteres acentuados.
Se necessário, restaure o backup de `/downloads/` e o link anterior do menu.

Entrega preparada para a hospedagem atual. Nenhum DNS foi alterado e a página
não foi instalada no domínio sem acesso à hospedagem.
