#:after:account/account:section:otras_tareas_contables#

Balance de situación y pérdidas y ganancias
===========================================

Tanto para sacar un balance de situación como un pérdidas y ganancias debemos
abrir la opción de menú *Contabilidad* > *Informes* > *Informes de balances
contables*. Veremos que en Tryton, este tipo de informes es posible calcularlos
y dejarlos almacenados como una foto del sistema en una fecha determinada. En
lugar de ser un informe en PDF que sacamos y debemos guardar, los balances
estarán siempre disponibles para ser consultados, sea cual fuere la fecha en la
que los calculamos.
Así pues, una vez hemos entrado en Informes de balances contables debemos hacer
clic en nuevo.

En el formulario del informe de balance debemos dar nombre al informe así como
seleccionar qué informe queremos (tipo de balance o pérdidas y ganancias) y los
períodos que queremos que incorpore.

.. (IMATGE) A continuación puede ver un ejemplo de un balance abreviado para el
   primer trimestre del año 2014 comparado con el primer trimestre del año 2013:

Una vez seleccionados los parámetros deseados, al pulsar en el botón *Calcular*
se rellenará toda la información en la pestaña *Líneas*. Estos datos estarán
almacenados y siempre disponibles para ser consultados. En la columna *Valor*
*actual* podemos ver el resultado aplicado para el primer período que hayamos
seleccionado  y en *Valor* *anterior* vemos el resultado aplicado al segundo
período seleccionado.

.. (en el ejemplo los tres primeros meses del año 2014)
   (en el ejemplo los tres primeros meses del año 2013)

Cómo encontrar de dónde salen los datos
---------------------------------------

Una vez calculado un balance o un informe de pérdidas y ganancias, es probable
que nos preguntemos de dónde sale alguno o varios de los cálculos. Para
encontrarlo solamente debemos pulsar en el botón *Abrir detalles*, se nos
abrirá un asistente, dónde seleccionar de qué período (*Actual* o *Anterior*)
queremos ver los detalles y si queremos ver los datos por cuenta o bien todos
los apuntes contables.

.. Imagen de ejemplo de asistente

Cambiar o definir una nueva plantilla de balance
------------------------------------------------

A pesar de que en Tryton ya tenemos definidas las plantillas oficiales de
balance y pérdidas y ganancias (versiones Abreviada, Normal y PYME), así como el
*Estado de ingresos y gastos reconocidos*, es posible crear nuestras propias
plantillas. Bien sean creadas de cero o, lo que es más habitual, sean creadas a
partir de otra ya existente. Esto nos permite sacar mensualmente, por ejemplo,
un informe de pérdidas y ganancias con los detalles de determinadas cuentas,
que son de nuestro especial interés.

Para ello debemos dirigirnos al menú *Contabilidad*> *Plantillas de balances
contables*. En caso de querer modificar una plantilla existente debemos
seleccionarla y duplicarla a través del menú de la caja de herramientas.

.. Imagen de ejemplo con el procedimiento de duplicación

Sobre el documento ya duplicado podemos añadir o quitar líneas, así como
establecer las cuentas a utilizar para el primer y segundo período.

.. Campos *Fórmula del ejercicio fiscal 1 y 2* que podemos encontrar dentro de
   las líneas. Se muestra imagen mostrando campos, como podemos observar:

Es posible indicar cuentas distintas para el primer y segundo período. Esto es
especialmente útil en caso de cambio de cuentas de un año a otro. También
podemos observar que la definición de cuentas sigue la misma estructura que los
documentos oficiales del BOE.

