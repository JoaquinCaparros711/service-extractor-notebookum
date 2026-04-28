# Service Extractor NotebookUm

Este microservicio se encarga de **Extraer el texto de los documentos PDF** para el sistema NotebookUm.

## Responsabilidades
- Recibe archivos PDF.
- Utiliza la librería `docling` para leer y estructurar el texto.
- Devuelve el contenido extraído en formato JSON.

## Ejecución con Docker
```bash
docker-compose up -d --build
```
El servicio estará disponible internamente en el puerto `5001`.
