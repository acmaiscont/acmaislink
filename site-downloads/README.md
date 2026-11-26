# Download do ACMAIS LINK no site

Use um único botão com o texto **Baixar ACMAIS LINK para Windows**. O endereço
acompanha a versão pública mais recente no GitHub. O mesmo instalador serve para
primeira instalação e atualização manual.
[Download direto de Instalar-ACMAIS-LINK.exe](https://github.com/acmaiscont/acmaislink/releases/latest/download/Instalar-ACMAIS-LINK.exe)

Depois de editar o site, abra a página por HTTPS e confirme que o botão baixa
`Instalar-ACMAIS-LINK.exe`. Em cada lançamento, compare o SHA-256 do arquivo
baixado com o valor publicado na Release.

## Modelo histórico

A pasta `dist/` guarda a página da versão 1.1.1, com dois botões de download.
Para reaproveitar o leiaute, adapte o conteúdo ao instalador único e use o link
permanente acima. Abra a prévia a partir da raiz do repositório.

```powershell
python -m http.server 8768 --bind 127.0.0.1 --directory site-downloads/dist
```

Abra `http://127.0.0.1:8768/`. Antes de publicar, confira a navegação por
teclado e se a página funciona em telas estreitas.
