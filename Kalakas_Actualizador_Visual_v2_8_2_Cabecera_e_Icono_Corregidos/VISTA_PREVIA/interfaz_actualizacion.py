"""Ventana de actualización para Kalaka's Soft · Juegos Torrent.

Interfaz Tkinter pura: no realiza descargas ni reemplazos. El módulo
actualizador.py existente conserva toda la lógica y las verificaciones.
"""
from __future__ import annotations

import tkinter as tk
from math import sqrt

FONDO = '#101722'
CABECERA = '#152337'
TARJETA = '#1d2b3d'
TARJETA_BORDE = '#30445c'
BLANCO = '#f3f7fd'
GRIS = '#a8b9cc'
TENUE = '#8195ac'
VERDE = '#54dfa0'
AZUL = '#55a5ff'
TURQUESA = '#32d3c2'

# Icono de refrescar antialias integrado (no necesita archivos PNG externos).
_ICONO_REFRESCAR_PNG = (
    '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'
 )


def _redondeado(canvas, x1, y1, x2, y2, radio, **kwargs):
    """Rectángulo redondeado sin bibliotecas externas."""
    radio = max(0, min(radio, (x2-x1)/2, (y2-y1)/2))
    puntos = [x1+radio,y1, x2-radio,y1, x2,y1, x2,y1+radio,
              x2,y2-radio, x2,y2, x2-radio,y2, x1+radio,y2,
              x1,y2, x1,y2-radio, x1,y1+radio, x1,y1]
    return canvas.create_polygon(puntos, smooth=True, splinesteps=18, **kwargs)


class BarraDescarga(tk.Canvas):
    """Barra de progreso real, con degradado y extremos redondeados."""
    def __init__(self, parent):
        super().__init__(parent, height=18, bg=TARJETA, bd=0,
                         highlightthickness=0)
        self.porcentaje = 0.0
        self.bind('<Configure>', lambda _event: self._dibujar())

    def set_value(self, value):
        self.porcentaje = max(0.0, min(100.0, float(value)))
        self._dibujar()

    def _dibujar(self):
        self.delete('all')
        ancho = self.winfo_width()
        alto = self.winfo_height()
        if ancho < 15 or alto < 10:
            return

        x1, y1, x2, y2 = 1, 2, ancho - 2, alto - 3
        _redondeado(self, x1, y1, x2, y2, 7,
                    fill='#2c4057', outline='#39506b', width=1)

        lleno = (x2 - x1 - 4) * self.porcentaje / 100
        if lleno <= 0:
            return

        fx1, fy1 = x1 + 2, y1 + 2
        fx2, fy2 = fx1 + lleno, y2 - 2
        radio = min((fy2 - fy1) / 2, (fx2 - fx1) / 2)
        centro_y = (fy1 + fy2) / 2
        color_inicio = (85, 165, 255)
        color_fin = (50, 211, 194)

        # Cada columna del degradado queda RECORTADA a la misma cápsula.
        # No hay óvalos superpuestos ni líneas que sobresalgan de la punta.
        for x in range(int(fx1), int(fx2) + 1):
            posicion = x + 0.5
            if posicion > fx2:
                continue
            if posicion < fx1 + radio:
                distancia = fx1 + radio - posicion
            elif posicion > fx2 - radio:
                distancia = posicion - (fx2 - radio)
            else:
                distancia = 0
            if distancia >= radio:
                continue
            semialto = sqrt(max(0, radio * radio - distancia * distancia))
            arriba = max(fy1, centro_y - semialto)
            abajo = min(fy2, centro_y + semialto)
            avance = (posicion - fx1) / max(1, fx2 - fx1)
            rgb = tuple(round(a + (b - a) * avance)
                        for a, b in zip(color_inicio, color_fin))
            color = '#%02x%02x%02x' % rgb
            self.create_line(x + 0.5, arriba, x + 0.5, abajo,
                             fill=color, width=1, capstyle=tk.BUTT)


class VentanaActualizacion(tk.Toplevel):
    """Presenta oferta y avance; las acciones reales se inyectan con callbacks."""
    def __init__(self, parent, version_actual, version_nueva, on_start, on_cancel):
        super().__init__(parent)
        self.version_actual = str(version_actual)
        self.version_nueva = str(version_nueva)
        self._on_start = on_start
        self._on_cancel = on_cancel
        self._modo = 'oferta'
        self._cancelando = False
        self.title("Kalaka's Soft | Actualizador")
        self.configure(bg=FONDO)
        self.resizable(False,False)
        self.transient(parent)
        self.protocol('WM_DELETE_WINDOW', self._cerrar)
        self._armar()
        self._mostrar_oferta()
        self.update_idletasks()
        ancho, alto = 548, 510
        try:
            x = parent.winfo_rootx()+max(0,(parent.winfo_width()-ancho)//2)
            y = parent.winfo_rooty()+max(0,(parent.winfo_height()-alto)//2)
        except tk.TclError:
            x,y=100,100
        x=max(0,min(x,self.winfo_screenwidth()-ancho))
        y=max(0,min(y,self.winfo_screenheight()-alto))
        self.geometry(f'{ancho}x{alto}+{x}+{y}')
        self._asegurar_alto()
        self.lift()
        self.focus_set()

    def _asegurar_alto(self):
        # Mantener visibles los botones con escalado de Windows 125/150/200%.
        self.update_idletasks()
        requerido = max(510, self.winfo_reqheight()+20)
        actual = self.winfo_height()
        if requerido > actual:
            nuevo = min(requerido, self.winfo_screenheight()-35)
            if nuevo > actual:
                y = max(0, self.winfo_y()-(nuevo-actual)//2)
                self.geometry(f'{self.winfo_width()}x{nuevo}+{self.winfo_x()}+{y}')

    def _armar(self):
        # La cabecera se adapta a la altura real de las fuentes de Windows.
        # Una altura fija de 116 px cortaba el subtítulo en algunos equipos.
        header=tk.Frame(self,bg=CABECERA)
        header.pack(fill='x')
        insignia=tk.Canvas(header,width=57,height=57,bg=CABECERA,highlightthickness=0)
        insignia.pack(side='left',padx=(27,17),pady=(26,26))
        _redondeado(insignia,2,2,54,54,15,fill='#24415b',outline='#426587',width=1)
        self._icono_refrescar=tk.PhotoImage(data=_ICONO_REFRESCAR_PNG,format='png')
        insignia.create_image(28,28,image=self._icono_refrescar)
        titulos=tk.Frame(header,bg=CABECERA)
        titulos.pack(side='left',fill='y',pady=(23,23))
        tk.Label(titulos,text="KALAKA'S SOFT  /  JUEGOS TORRENT",bg=CABECERA,
                 fg=TURQUESA,font=('Segoe UI',9,'bold')).pack(anchor='w')
        self.titulo=tk.Label(titulos,text='Actualización disponible',bg=CABECERA,
                             fg=BLANCO,font=('Segoe UI',17,'bold'))
        self.titulo.pack(anchor='w',pady=(7,0))
        self.subtitulo=tk.Label(titulos,text='Una nueva versión está lista para instalar',
                                bg=CABECERA,fg=GRIS,font=('Segoe UI',10))
        self.subtitulo.pack(anchor='w',pady=(4,0))

        contenido=tk.Frame(self,bg=FONDO)
        contenido.pack(fill='both',expand=True,padx=25,pady=(21,0))

        self.versiones=tk.Frame(contenido,bg=TARJETA,highlightbackground=TARJETA_BORDE,
                               highlightthickness=1,height=84)
        self.versiones.pack(fill='x')
        self.versiones.pack_propagate(False)
        fila=tk.Frame(self.versiones,bg=TARJETA)
        fila.pack(fill='x',padx=21,pady=15)
        anterior=tk.Frame(fila,bg=TARJETA)
        anterior.pack(side='left',fill='x',expand=True)
        tk.Label(anterior,text='VERSIÓN INSTALADA',bg=TARJETA,fg=TENUE,
                 font=('Segoe UI',9,'bold')).pack(anchor='w')
        tk.Label(anterior,text='v'+self.version_actual,bg=TARJETA,fg=BLANCO,
                 font=('Segoe UI',16,'bold')).pack(anchor='w',pady=(4,0))
        tk.Label(fila,text='→',bg=TARJETA,fg=TURQUESA,
                 font=('Segoe UI',22,'bold')).pack(side='left',padx=13)
        nueva=tk.Frame(fila,bg=TARJETA)
        nueva.pack(side='left',fill='x',expand=True)
        tk.Label(nueva,text='NUEVA VERSIÓN',bg=TARJETA,fg=TENUE,
                 font=('Segoe UI',9,'bold')).pack(anchor='w')
        tk.Label(nueva,text='v'+self.version_nueva,bg=TARJETA,fg=VERDE,
                 font=('Segoe UI',16,'bold')).pack(anchor='w',pady=(4,0))

        self.cuerpo=tk.Frame(contenido,bg=FONDO)
        self.cuerpo.pack(fill='both',expand=True,pady=(17,0))

        footer=tk.Frame(self,bg=FONDO)
        footer.pack(fill='x',padx=25,pady=(0,20))
        self.aviso=tk.Label(footer,text='',bg=FONDO,fg=TENUE,
                            justify='left',anchor='w',font=('Segoe UI',9),wraplength=205)
        self.aviso.pack(side='left',fill='x',expand=True)
        self.boton_secundario=tk.Button(footer,text='Ahora no',command=self._cerrar,
                      bg='#263649',fg=BLANCO,activebackground='#354961',
                      activeforeground=BLANCO,relief='flat',bd=0,cursor='hand2',
                      font=('Segoe UI',10),padx=16,pady=10)
        self.boton_secundario.pack(side='right')
        self.boton_principal=tk.Button(footer,text='Actualizar ahora',command=self._comenzar,
                      bg=VERDE,fg='#10251c',activebackground='#78f5b6',
                      activeforeground='#10251c',relief='flat',bd=0,cursor='hand2',
                      font=('Segoe UI',10,'bold'),padx=17,pady=10)
        self.boton_principal.pack(side='right',padx=(0,10))

    def _limpiar_cuerpo(self):
        for widget in self.cuerpo.winfo_children():
            widget.destroy()

    def _mostrar_oferta(self):
        self._modo='oferta'
        self._limpiar_cuerpo()
        tk.Label(self.cuerpo,text='ACTUALIZACIÓN SEGURA',bg=FONDO,fg=VERDE,
                 font=('Segoe UI',10,'bold')).pack(anchor='w')
        tk.Label(self.cuerpo,text='Descargaremos la nueva versión desde GitHub y\n'
                 'verificaremos su integridad antes de instalarla.',
                 bg=FONDO,fg=BLANCO,font=('Segoe UI',11),justify='left').pack(anchor='w',pady=(10,14))
        tk.Label(self.cuerpo,text='✓  Tus juegos, biblioteca y configuraciones se conservan.\n'
                 '✓  El programa se reiniciará al finalizar.',bg=FONDO,fg=GRIS,
                 font=('Segoe UI',10),justify='left').pack(anchor='w')
        self.aviso.config(text='Descarga verificada con SHA-256.\nConexión HTTPS segura.')
        self.boton_principal.config(text='Actualizar ahora',state='normal')
        self.boton_principal.pack(side='right',before=self.boton_secundario,padx=(0,10))
        self.boton_secundario.config(text='Ahora no',state='normal',command=self._cerrar)

    def _comenzar(self):
        if self._modo != 'oferta':
            return
        self._modo='descargando'
        self.titulo.config(text='Actualizando Juegos Torrent')
        self.subtitulo.config(text='Preparando la nueva versión de forma segura')
        self._limpiar_cuerpo()
        fases=tk.Frame(self.cuerpo,bg=FONDO)
        fases.pack(fill='x',pady=(1,18))
        self._etapas=[]
        for idx,nombre in enumerate(('DESCARGA','VERIFICACIÓN','INSTALACIÓN')):
            cont=tk.Frame(fases,bg=FONDO)
            cont.pack(side='left',expand=True,fill='x')
            circulo=tk.Canvas(cont,width=30,height=30,bg=FONDO,highlightthickness=0)
            circulo.pack()
            etiqueta=tk.Label(cont,text=nombre,bg=FONDO,fg=TENUE,
                              font=('Segoe UI',8,'bold'))
            etiqueta.pack(pady=(6,0))
            self._etapas.append((circulo,etiqueta))
        tarjeta=tk.Frame(self.cuerpo,bg=TARJETA,highlightbackground=TARJETA_BORDE,
                         highlightthickness=1)
        tarjeta.pack(fill='x')
        fila=tk.Frame(tarjeta,bg=TARJETA)
        fila.pack(fill='x',padx=17,pady=(16,10))
        self.estado=tk.Label(fila,text='Conectando con GitHub...',bg=TARJETA,
                             fg=BLANCO,font=('Segoe UI',11,'bold'))
        self.estado.pack(side='left')
        self.porcentaje=tk.Label(fila,text='0%',bg=TARJETA,fg=VERDE,
                                 font=('Segoe UI',16,'bold'))
        self.porcentaje.pack(side='right')
        self.barra=BarraDescarga(tarjeta)
        self.barra.pack(fill='x',padx=17,pady=(0,9))
        self.detalle=tk.Label(tarjeta,text='Esperando respuesta del servidor...',bg=TARJETA,
                              fg=GRIS,font=('Segoe UI',9))
        self.detalle.pack(anchor='w',padx=17,pady=(0,15))
        self.aviso.config(text='Los archivos se verifican antes\nde reemplazar el ejecutable.')
        self.boton_principal.pack_forget()
        self.boton_secundario.config(text='Cancelar',state='normal',command=self._cancelar)
        self._dibujar_etapas(0)
        self._asegurar_alto()
        self._on_start()

    def _dibujar_etapas(self, activa):
        for i,(canvas,label) in enumerate(self._etapas):
            canvas.delete('all')
            completo = i<activa
            color=VERDE if completo else AZUL if i==activa else '#304259'
            canvas.create_oval(2,2,28,28,fill=color,outline='')
            canvas.create_text(15,15,text='✓' if completo else str(i+1),
                               fill='#11241b' if completo else BLANCO,
                               font=('Segoe UI',11,'bold'))
            label.config(fg=VERDE if completo else BLANCO if i==activa else TENUE)

    def set_progress(self, done, total):
        if self._modo not in ('descargando','verificando'):
            return
        total=max(1,int(total))
        done=max(0,min(int(done),total))
        porcentaje=100.0*done/total
        self.barra.set_value(porcentaje)
        self.porcentaje.config(text=f'{porcentaje:.0f}%')
        self.detalle.config(text=f'{done/1048576:.1f} MB de {total/1048576:.1f} MB descargados')
        if done>=total:
            self._modo='verificando'
            self._dibujar_etapas(1)
            self.estado.config(text='Verificando integridad SHA-256...')
            self.subtitulo.config(text='La descarga terminó; comprobando seguridad')
        else:
            self.estado.config(text='Descargando actualización...')

    def set_preparing(self):
        if self._modo not in ('descargando','verificando'):
            return
        self._modo='preparando'
        self._dibujar_etapas(1)
        self.estado.config(text='Comprobando el nuevo ejecutable...')
        self.detalle.config(text='Descarga verificada. Preparando reinicio seguro.')
        self.porcentaje.config(text='100%')
        self.barra.set_value(100)
        self.subtitulo.config(text='Preparando el reemplazo del programa')
        self.boton_secundario.config(text='Esperá...',state='disabled')
        self.aviso.config(text='La instalación continuará cuando\nse cierre la versión actual.')

    def set_restarting(self):
        if self._modo != 'preparando':
            return
        self._modo='reiniciando'
        self._dibujar_etapas(2)
        self.estado.config(text='Cerrando para instalar...')
        self.detalle.config(text='El actualizador continuará en segundo plano.')
        self.subtitulo.config(text='El programa volverá a abrirse automáticamente')
        self.boton_secundario.config(text='Reiniciando...',state='disabled')

    def _cancelar(self):
        if self._cancelando or self._modo not in ('descargando','verificando'):
            return
        self._cancelando=True
        self.boton_secundario.config(text='Cancelando...',state='disabled')
        self.estado.config(text='Cancelando actualización...')
        self._on_cancel()

    def _cerrar(self):
        if self._modo=='oferta':
            self.destroy()
        elif self._modo in ('descargando','verificando'):
            self._cancelar()
        # Durante la preparación/instalación no cerrar: se está haciendo el traspaso.
