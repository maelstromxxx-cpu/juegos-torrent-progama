# Guía de Hipervisores

Esta página está en desarrollo y será actualizada próximamente.  
Este artículo está parcialmente basado en el artículo de RessourectoR (administrador del sitio cs.rin.ru):  
[https://cs.rin.ru/forum/viewtopic.php?f=10&t=156407](https://cs.rin.ru/forum/viewtopic.php?f=10&t=156407)  

Recomiendo encarecidamente abrirlo y leerlo al menos una vez. Es más complejo que esta página y abarca más temas de seguridad.

---

## ¿Qué son los Cracks de Hipervisor?

Un crack o *bypass* de hipervisor para Denuvo se refiere a técnicas avanzadas que aprovechan la virtualización a un nivel muy bajo (a menudo utilizando un hipervisor personalizado o modificado) para interferir en cómo la protección supervisa el sistema. Denuvo depende en gran medida de comprobaciones de integridad, análisis de tiempos y la detección de entornos de depuración o emulación. Un enfoque basado en hipervisor permite a un atacante situarse "por debajo" del sistema operativo, controlando de forma transparente el comportamiento de la CPU, interceptando instrucciones y enmascarando los signos de análisis sin modificar directamente el ejecutable protegido.

En lugar de parchear el binario del juego, el hipervisor puede emular o alterar instrucciones específicas de la CPU, falsificar los resultados de tiempo u ocultar puntos de interrupción (*breakpoints*) y cambios en la memoria, engañando eficazmente a Denuvo para que crea que todo se está ejecutando en un sistema normal y sin alteraciones. Esto hace que la protección sea mucho más difícil de detectar o de reaccionar ante ella, ya que sus comprobaciones se manejan fuera de su visibilidad. Estos métodos son extremadamente complejos y suelen ser explorados por ingenieros inversivos altamente cualificados, ya que requieren un conocimiento profundo de la virtualización de CPU, los componentes internos del núcleo (*kernel*) y los mecanismos anti-manipulación (*anti-tamper*).

Oficialmente, solo los controladores (*drivers*) firmados pueden funcionar a un nivel tan bajo. Debido a la naturaleza de piratería de los controladores del hipervisor de Denuvo, nunca recibirán un certificado aprobado por Microsoft. Y es por eso que, para usar tales "cracks", es necesario realizar ciertas modificaciones en la configuración de seguridad del sistema que se detallan a continuación. Ten en cuenta que estos cambios están pensados para realizarse de forma temporal, durante tu sesión de juego, y luego deben revertirse después de salir del juego.

---

## Componentes de seguridad basados en virtualización de Windows

En los sistemas modernos con Arranque Seguro (*Secure Boot*), TPM 2.0 y capacidades de virtualización asistida por hardware, Windows 10 y 11 habilitan (en su mayoría*, por defecto) diversas soluciones de seguridad mediante la Seguridad basada en Virtualización (VBS). VBS es un término paraguas para el uso de un hipervisor nativo (*bare-metal*), el hipervisor de Windows, para crear espacios virtuales aislados que estén seguros incluso frente a un SO completamente comprometido, en los cuales se ejecutan estos componentes de seguridad y supervisan el SO o almacenan información confidencial.

Los siguientes componentes de Windows son dichas soluciones de seguridad:

- **Integridad de memoria (HVCI):** Realiza comprobaciones para detectar modificaciones maliciosas o inesperadas del código del núcleo de Windows y restringe las asignaciones sospechosas de memoria del núcleo. Por ejemplo, RessourectoR imagina que esto podría proteger contra software malicioso que se ejecute con privilegios de administrador e intente modificar archivos del sistema, o contra vulnerabilidades de seguridad de memoria en aplicaciones ejecutadas por el usuario.
- **Credential Guard:** Almacena credenciales de acceso (como contraseñas, datos de autenticación, datos biométricos, etc.) en un entorno aislado.
- **Windows Hello:** Permite iniciar sesión con métodos convenientes como un PIN corto, reconocimiento facial o escaneo de huellas dactilares. RessourectoR no ha encontrado una fuente directa sobre esto, pero probablemente prefiera Credential Guard para almacenar sus datos altamente confidenciales. Los métodos de inicio de sesión que proporciona tienden a fallar cuando se deshabilitan algunos de los componentes anteriores. También está protegido por System Guard, si este se encuentra habilitado.
- **System Guard (Secure Launch):** Un marco avanzado de endurecimiento del sistema que protege el proceso de arranque del SO y el Modo de Gestión del Sistema (SMM, comúnmente utilizado por la BIOS para ejecutar software de configuración de hardware) frente a rootkits (presumiblemente sofisticados). Estos rootkits podrían comprometer el hipervisor en sí, por lo que esta protección cuenta con la asistencia de varias características de seguridad por hardware de los procesadores modernos. Con el respaldo de TPM 2.0, esto también permite supervisar continuamente la integridad del sistema (incluyendo los otros componentes de seguridad mencionados aquí) después del arranque y verificarla desde un sistema remoto.
  - Por lo que RessourectoR pudo averiguar, esto es de vanguardia y no está habilitado por defecto.
- A pesar de cumplirse los requisitos de hardware y arranque, a veces Windows parece fallar al habilitar funciones que se supone deberían activarse automáticamente, como VBS y la integridad de memoria.

Sin el hipervisor de Windows, ninguna de estas características de seguridad puede utilizarse. Por diseño, el hipervisor no se puede deshabilitar directamente. En su lugar, todas las características anteriores que desean utilizar VBS indican que este debe habilitarse, lo que a su vez carga el hipervisor. Por lo tanto, debemos deshabilitar todas esas características para evitar que se cargue el hipervisor de Windows.

También es necesario añadir una opción de arranque que impida que Hyper-V cargue el hipervisor.

---

## ¿Quiero jugar a ese nuevo juego protegido por Denuvo, es seguro deshabilitar todo esto y usar un crack de hipervisor?

No hay una respuesta sencilla. Esta es la postura personal de RessourectoR como alguien con 10 años de experiencia en administración de sistemas centrada en la seguridad y solo un interés casual en los videojuegos.

Es cierto que las amenazas más comunes son el malware de robo de información (*infostealer*) procedente de botones de descarga falsos, el ransomware que cifra tus archivos o unirse a una botnet DDoS. Se supone que dicho malware normalmente no está interesado en una mayor escalada de privilegios o sabotaje de hardware si ya puede acceder a lo que necesita. También es cierto que la mejor protección contra este malware es un buen bloqueador de anuncios, mantenerse en sitios de confianza y la educación del usuario.

Los usuarios de PC más experimentados desarrollan una falsa sensación de seguridad al ver con qué éxito evitan las infecciones de malware por "ser listos". Argumentan que no necesitan todas estas características de seguridad restrictivas y paternalistas ni los antivirus que solo molestan con falsos positivos, porque su historial libre de malware "demuestra" que saben lo que hacen. También argumentan que las amenazas más avanzadas no están dirigidas a usuarios domésticos, sino a redes corporativas, y que es muy poco probable que se interesen por ellos. Especialmente relevante para los jugadores: la virtualización puede reducir el rendimiento del sistema, y si eso se nota o no es también un punto de discusión.

El otro lado del argumento: Estarías deshabilitando tecnología que evolucionó a partir de décadas de investigación en seguridad, ignorando lo que los expertos consideran necesario hoy en día. Estarías renunciando voluntariamente a las protecciones contra clases comunes de vulnerabilidades de software y, si alguna vez contraes un malware más avanzado, este podrá atravesarlas sin problemas para que tu PC permanezca en una botnet por la eternidad o se propague más fácilmente a otros dispositivos de la red local. Si mucha gente elimina estas protecciones —especialmente DSE e integridad de memoria— para jugar, uno de los principales casos de uso de las PC con Windows en el hogar, podría valer la pena el esfuerzo para los autores de malware apuntar a este tipo de configuraciones. El uso generalizado de cracks HV podría fomentar lanzamientos falsos manipulados, ya que se puede esperar que las personas que los descargan deshabiliten toda protección, incluida la exclusión del antivirus. El conocimiento y el esfuerzo necesarios para tomar precauciones y verificar los archivos correctamente son mayores que con las amenazas comunes, y las consecuencias potenciales son mucho más graves.

Aparte de las características de Windows desactivadas, incluso si confías en los autores del controlador del hipervisor e incluso si lo compilas tú mismo desde el código fuente, una vulnerabilidad grave en su código podría proporcionar instantáneamente acceso total e indetectable a tu sistema.

Si ese juego vale la pena o no frente a estos riesgos, es algo que en última instancia tendrás que decidir por ti mismo.

---

## ¿Qué hay dentro de esos cracks?

Básicamente, cualquier *bypass*/crack de hipervisor moderno consta de dos partes:

1. **VBS.cmd:** Un script de línea de comandos especial que comprueba tu configuración actual y la modifica para preparar tu sistema para los cracks de HV. Este script es universal para todos los juegos con HV y se desarrolla por separado; no depende de los cracks reales de los juegos. Puedes descargar la última versión a continuación:
   - Versión actual: `v2.0` (Actualizado el 29 de octubre de 2026)
   - Registro de cambios:
2. **El Crack / Bypass en sí:** Consiste en ejecutables (`.exe`) y librerías (`.dll`) que realizan el reenvío/puente real de Denuvo, además de otras DLLs adicionales como el emulador Goldberg Steam para superar la protección subyacente de Steam.
   - Estos archivos funcionan únicamente para las versiones de juego específicas para las que fueron creados. No funcionarán en una versión de juego diferente ni en otros juegos.

---

## Otras actualizaciones de software

- **Actualizado `hypervisor-launcher.exe` v1.3.1**
  - Soluciona el problema de reinicio de PC en algunos sistemas, principalmente en procesadores Intel. Este es un espejo de la página oficial de GitHub.
  - La versión anterior de `hypervisor-launcher.exe` se utiliza en muchos lanzamientos de *DenuvOwO* y en algunos de mis *repacks* publicados antes del 28 de marzo de 2026. Todos los *repacks* de HV posteriores a esa fecha con esta versión del lanzador utilizan la compilación actualizada. Puedes descargar y probar la nueva versión **SOLO si tienes un problema de lanzamiento**, no es necesario reemplazarla si todo te funciona bien.
  - Mis *repacks* con la versión anterior de `hypervisor-launcher.exe`:
    - *Assassin’s Creed Shadows*
    - *Hello Kitty Island Adventure*
    - *NBA 2K26*
    - *Stellar Blade*

---

## Requisitos previos

Tu CPU debe ser compatible con una de estas dos técnicas de virtualización: **VT-x** para Intel o **AMD-V (SVM)** para AMD.  
Busca en Google si tu modelo de CPU es compatible con la virtualización para saber si puedes jugar a juegos con HV.  
Antes de continuar con los cracks de HV, revisa tu BIOS para habilitar estas tecnologías.

---

## ¿Necesito deshabilitar el Arranque Seguro (*Secure Boot*) o usar EfiGuard?

No. Los *bypasses* de HV actuales no requieren dichos cambios.

---

*Guía creada por FitGirl Repack*