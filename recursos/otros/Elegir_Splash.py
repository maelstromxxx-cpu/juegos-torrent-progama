# Selector de Splash - Kalaka's Soft
from pathlib import Path
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk

BASE = Path(__file__).resolve().parent
ASSETS = BASE / 'recursos'
CHOICE = ASSETS / 'splash_seleccion.txt'
root = tk.Tk()
root.title("Kalaka's Soft | Elegir Splash")
root.configure(bg='#121923')
root.geometry('850x420')
root.resizable(False, False)
try:
    current = CHOICE.read_text(encoding='utf-8').strip()
except OSError:
    current = '1'
selected = tk.StringVar(value=current if current in ('1', '2') else '1')
tk.Label(root, text='ELEGÍ TU PANTALLA DE INICIO', font=('Segoe UI', 18, 'bold'),
         fg='#f2f6fa', bg='#121923').pack(pady=(16, 4))
tk.Label(root, text='El cambio se verá la próxima vez que abras Juegos Torrent.',
         font=('Segoe UI', 10), fg='#b7c1ca', bg='#121923').pack()
row = tk.Frame(root, bg='#121923')
row.pack(pady=18)
photos = []
for n, label in [('1', 'Original PC Gaming'), ('2', 'Collage de juegos')]:
    frame = tk.Frame(row, bg='#1c2632', padx=12, pady=12)
    frame.pack(side='left', padx=12)
    path = ASSETS / f'splash_opcion_{n}.png'
    if path.is_file():
        with Image.open(path) as im:
            im = im.convert('RGB')
            im.thumbnail((365, 210), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(im)
        photos.append(photo)
        tk.Label(frame, image=photo, bg='#1c2632').pack()
    else:
        tk.Label(frame, text='Imagen no encontrada', bg='#1c2632', fg='white',
                 width=40, height=12).pack()
    tk.Radiobutton(frame, text=label, variable=selected, value=n,
                   font=('Segoe UI', 11, 'bold'), fg='#f1f5f9', bg='#1c2632',
                   selectcolor='#263746', activebackground='#1c2632',
                   activeforeground='#5ae28c').pack(pady=(10, 0))
def save():
    try:
        ASSETS.mkdir(parents=True, exist_ok=True)
        CHOICE.write_text(selected.get() + '\n', encoding='utf-8')
    except OSError as exc:
        messagebox.showerror('Error', f'No se pudo guardar la elección:\n{exc}')
        return
    messagebox.showinfo('Listo', '¡Splash seleccionado! Se verá al próximo inicio.')
    root.destroy()
tk.Button(root, text='GUARDAR SELECCIÓN', command=save,
          bg='#208a55', fg='white', activebackground='#32ad70',
          font=('Segoe UI', 11, 'bold'), relief='flat', padx=24, pady=10,
          cursor='hand2').pack()
root.mainloop()
