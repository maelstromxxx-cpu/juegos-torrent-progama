"""Vista previa local del actualizador. NO descarga ni instala nada.

Ejecutar: python Vista_Previa_Actualizador.py
"""
import tkinter as tk
from interfaz_actualizacion import VentanaActualizacion

root = tk.Tk()
root.title("Kalaka's Soft · Prueba de interfaz")
root.configure(bg='#101722')
root.geometry('460x240')
root.resizable(False,False)

cabecera=tk.Label(root,text='VISTA PREVIA DEL ACTUALIZADOR',
                  font=('Segoe UI',15,'bold'),bg='#101722',fg='#f3f7fd')
cabecera.pack(pady=(36,12))
tk.Label(root,text='Simulación visual: no descarga, no modifica ni instala archivos.',
         font=('Segoe UI',10),bg='#101722',fg='#a8b9cc').pack()

ventana=[None]
trabajo=[None]

def abrir():
    if ventana[0] is not None and ventana[0].winfo_exists():
        ventana[0].lift()
        return
    progreso=[0]
    def detener():
        if trabajo[0] is not None:
            root.after_cancel(trabajo[0])
            trabajo[0]=None
        if ventana[0] is not None and ventana[0].winfo_exists():
            ventana[0].destroy()

    def avanzar():
        dlg=ventana[0]
        if dlg is None or not dlg.winfo_exists():
            return
        progreso[0]=min(100,progreso[0]+2)
        dlg.set_progress(progreso[0]*1048576,100*1048576)
        if progreso[0]<100:
            trabajo[0]=root.after(90,avanzar)
        else:
            trabajo[0]=root.after(1100,preparar)

    def preparar():
        if ventana[0] is not None and ventana[0].winfo_exists():
            ventana[0].set_preparing()
            trabajo[0]=root.after(1400,reiniciar)

    def reiniciar():
        if ventana[0] is not None and ventana[0].winfo_exists():
            ventana[0].set_restarting()
            trabajo[0]=root.after(2300,detener)

    def comenzar():
        trabajo[0]=root.after(150,avanzar)

    ventana[0]=VentanaActualizacion(root,'2.8.1','2.8.2',comenzar,detener)

boton=tk.Button(root,text='Ver ventana de actualización',command=abrir,
                bg='#54dfa0',fg='#10251c',relief='flat',font=('Segoe UI',11,'bold'),
                padx=22,pady=12,cursor='hand2')
boton.pack(pady=25)
root.mainloop()
