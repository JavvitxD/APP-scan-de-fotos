# Instrucciones para Cowork: digitalizar el libro con el Escáner de Libros

> **Para la persona:** guarde este archivo en la misma carpeta donde están las fotos (o en la
> carpeta del programa) y, en Cowork, dele acceso a esa carpeta y escriba:
> *«Lee INSTRUCCIONES_COWORK.md y arma el plan de acción»*.

---

## 1. Contexto (para Claude en Cowork)

- La persona tiene **unas 1.200 fotos** de las páginas de uno o varios libros en español. Son
  fotos de **fotocopias** (no del libro original), tomadas con el celular.
- Para transcribirlas usa el programa **Escáner de Libros** (`EscanerLibros.exe`), que ya está
  en su computador. El programa:
  - limpia cada foto (recorta, endereza, quita el fondo gris y las manchas),
  - separa solo las fotos que traen dos páginas,
  - lee el texto **sin internet** (Tesseract),
  - permite revisar y corregir cada página,
  - exporta a **PDF buscable**, **Word** y **texto (.txt)**.
- Los libros quedan guardados en `EscanerLibros\Proyectos\<nombre del libro>\`. Dentro de cada
  uno: `originales\`, `procesadas\`, `paginas\` (texto en JSON) y `proyecto.json`.
- Más detalles de uso: `INSTRUCCIONES.txt`, en la carpeta del programa.

## 2. Reglas importantes

1. **No borrar, mover ni renombrar las fotos originales.** Si hace falta ordenar, **copiar** a
   carpetas nuevas. Antes de cualquier acción sobre muchos archivos, mostrar el plan y pedir
   confirmación.
2. **Privacidad:** las fotos y el texto no deben salir del computador. No subirlos a ningún
   servicio web.
3. **No transcribir las fotos con la IA.** La transcripción la hace el Escáner de Libros (gratis
   y local). Cowork organiza, lleva el control y revisa el texto que el programa exporta. Mirar
   solo unas pocas fotos de muestra cuando haga falta.
4. Hablar con la persona en español sencillo, paso a paso.

## 3. Lo que se pide

### Paso A — Inventario de las fotos
Revisar la carpeta de fotos e informar:
- Cuántas fotos hay, de qué tipo (JPG, PNG, HEIC…) y cuánto ocupan.
  *Ojo:* el programa **no abre HEIC** (formato del iPhone); si hay, avisar y proponer convertirlas
  a JPG (copias, sin tocar las originales).
- Si los nombres siguen un orden (IMG_0001, IMG_0002…) y si ese orden coincide con la fecha de
  la foto. Señalar huecos o saltos raros.
- Posibles **duplicados** (mismo tamaño y contenido, o nombres tipo «(1)», «copia»).
- Fotos sospechosas: muy pequeñas, muy oscuras o borrosas (revisar solo una muestra).
- Si parece haber **más de un libro** (por fechas, carpetas o cantidad), preguntarle a la persona.
  Unas 300 páginas por libro sugieren que 1.200 fotos pueden ser varios libros, repeticiones, o
  fotos con dos páginas cada una.

### Paso B — Organizar en lotes
Proponer una estructura, por ejemplo:

```
Libro digital\
  Libro 1 - <nombre>\
    Lote 01 (fotos 0001-0100)\
    Lote 02 (fotos 0101-0200)\
    ...
```

- Lotes de **unas 100 fotos**: se procesan en 5 a 15 minutos y se revisan en una sesión.
- **Un proyecto del Escáner por libro** (no por lote): los lotes se agregan uno tras otro al
  mismo proyecto, así al final sale un solo PDF por libro.
- Copiar (no mover) las fotos a los lotes, conservando el orden.

### Paso C — Hoja de seguimiento
Crear `Seguimiento.xlsx` (o `.csv`) con una fila por lote:

| Libro | Lote | Fotos (desde–hasta) | Agregado al programa | Procesado | Páginas revisadas | Notas |
|---|---|---|---|---|---|---|

Actualizarla cada vez que la persona cuente su avance. Para saber el estado real de un libro se
puede leer `Proyectos\<libro>\proyecto.json`: cada página tiene `"status"` igual a
`pendiente`, `transcrita`, `revisada` o `error`.

### Paso D — Guía para cada sesión de trabajo
Darle a la persona una lista corta para cada lote:
1. Abrir `EscanerLibros.exe` y el libro (o «Nuevo libro» la primera vez).
2. «Agregar fotos» → seleccionar todas las fotos del lote.
3. Revisar las miniaturas: orden, fotos giradas, páginas dobles mal partidas, repetidas.
4. «Procesar pendientes» (F5) y esperar.
5. Revisar las páginas con «Lectura dudosa» o en rojo («Error»); tomar de nuevo las fotos
   malas si hace falta.
6. Avisar a Cowork para actualizar el seguimiento.

### Paso E — Revisión del texto (cuando haya libros exportados)
Cuando la persona exporte un libro a `.txt` o Word, revisar ese texto y entregar una lista de
**páginas a corregir**: palabras sin sentido, letras raras (`|`, `~`, `»` sueltos), párrafos
cortados, páginas vacías o repetidas, números de página que saltan. Indicar el número de página
para que la persona lo corrija en el programa (no editar los archivos del proyecto directamente).

### Paso F — Plan y calendario
Con el inventario, proponer un plan realista: cuántos lotes, cuántos por sesión, tiempo
estimado (procesar ≈ 3 a 10 segundos por foto según el computador; revisar ≈ 1 a 3 minutos por
página), y en qué orden. Preguntar cuánto tiempo al día quiere dedicarle.

## 4. Primer mensaje esperado de Cowork
1. Resumen del inventario (Paso A).
2. Preguntas que necesite resolver (cuántos libros, si hay fotos repetidas que borrar, etc.).
3. Propuesta de lotes y plan, **sin ejecutar nada todavía**, esperando el «sí» de la persona.
