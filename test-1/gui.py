import tkinter as tk
from tkinter import ttk,messagebox
import threading,queue
import config as c
from robot_backend import Backend

PALETTE={"зелёный":"#b5dfbf","розовый":"#f0bfd5","синий":"#b6cfee","брак":"#edb8b8"}

class App:
    def __init__(self,root):
        self.root=root;root.title("ARM95 — назначения оператора");root.geometry("1120x800")
        self.events=queue.Queue();self.busy=False;self.failed=False
        self.plan=[];self.used=set();self.occupied=set();self.source=None;self.target=None;self.buttons={}
        self.category=tk.StringVar(value="зелёный");self.status=tk.StringVar(value="Не запущен")
        self.selection=tk.StringVar(value="Выберите исходную и приёмную ячейки")
        self.backend=Backend(lambda text:self.events.put(("log",text)),self.ask_worker)
        top=ttk.Frame(root,padding=12);top.pack(fill="x")
        ttk.Label(top,text="ARM95 | Управление упаковками",font=("Arial",18,"bold")).pack(side="left")
        self.start_button=ttk.Button(top,text="Включить / HOME",command=lambda:self.launch(self.backend.startup))
        self.start_button.pack(side="right")
        ttk.Label(root,textvariable=self.status).pack(anchor="w",padx=15)
        ttk.Label(root,text="Нет проверки маршрута. Закрытие окна не останавливает робот. Аварийная кнопка — на установке.",foreground="#a13232").pack(anchor="w",padx=15,pady=6)
        grids=ttk.Frame(root,padding=10);grids.pack(fill="x")
        self.grid(grids,"Исходная секция",list(c.SOURCE),"source")
        self.grid(grids,"Приёмная секция 1–9",list(range(1,10)),"target")
        self.grid(grids,"Приёмная секция 10–18",list(range(10,19)),"target")
        bar=ttk.Frame(root,padding=10);bar.pack(fill="x")
        ttk.Label(bar,text="Цвет / категория:").pack(side="left")
        ttk.Combobox(bar,textvariable=self.category,values=list(PALETTE),width=16).pack(side="left",padx=6)
        ttk.Button(bar,text="Добавить перенос",command=self.add).pack(side="left",padx=6)
        ttk.Button(bar,text="Удалить выбранный",command=self.remove).pack(side="left",padx=6)
        ttk.Label(root,textvariable=self.selection).pack(anchor="w",padx=15)
        self.table=ttk.Treeview(root,columns=("src","color","dst"),show="headings",height=6)
        for key,title in [("src","Откуда"),("color","Цвет / категория"),("dst","Куда")]:self.table.heading(key,text=title)
        self.table.pack(fill="x",padx=15,pady=8)
        bar=ttk.Frame(root,padding=10);bar.pack(fill="x")
        self.run_button=ttk.Button(bar,text="Выполнить указанные переносы",command=self.execute);self.run_button.pack(side="left")
        ttk.Button(bar,text="Очистить план",command=self.clear).pack(side="left",padx=8)
        self.count=tk.StringVar();ttk.Label(bar,textvariable=self.count).pack(side="right")
        self.logbox=tk.Text(root,height=9,state="disabled",wrap="word");self.logbox.pack(fill="both",expand=True,padx=15,pady=8)
        self.refresh();root.protocol("WM_DELETE_WINDOW",self.close);root.after(100,self.poll)

    def grid(self,parent,title,labels,kind):
        frame=ttk.LabelFrame(parent,text=title,padding=8);frame.pack(side="left",expand=True,fill="both",padx=5)
        for i,label in enumerate(labels):
            b=tk.Button(frame,text=str(label),width=11,height=3,bg="#eef1f5",command=lambda k=kind,l=label:self.choose(k,l))
            b.grid(row=i//3,column=i%3,padx=3,pady=3,sticky="nsew");self.buttons[kind,label]=b
        for i in range(3):frame.columnconfigure(i,weight=1)

    def choose(self,kind,label):
        if self.busy or self.failed:return
        if kind=="source":self.source=label
        else:self.target=label
        self.refresh()

    def refresh(self):
        for item in self.table.get_children():self.table.delete(item)
        for i,row in enumerate(self.plan):self.table.insert("","end",iid=str(i),values=row)
        for (kind,label),b in self.buttons.items():
            occupied=(kind=="source" and label in self.used) or (kind=="target" and label in self.occupied)
            b.config(bg="#aeb5bf" if occupied else "#eef1f5",relief="raised")
        for src,category,dst in self.plan:
            color=PALETTE.get(category,"#ded5f0")
            self.buttons["source",src].config(bg=color);self.buttons["target",dst].config(bg=color)
        for key in [("source",self.source),("target",self.target)]:
            if key in self.buttons:self.buttons[key].config(relief="sunken")
        self.selection.set(f"Исходная: {self.source or '—'} → Приёмная: {self.target or '—'}")
        self.count.set(f"План: {len(self.plan)} | выполнено: {len(self.used)} / {c.TOTAL_PACKAGES}")

    def add(self):
        if self.busy or self.failed:return
        category=self.category.get().strip().lower()
        if self.source is None or self.target is None or not category:
            messagebox.showwarning("Выбор","Выберите источник, категорию и назначение.");return
        if len(self.used)+len(self.plan)>=c.TOTAL_PACKAGES:
            messagebox.showwarning("План","В этой сессии допускается до 6 упаковок.");return
        if self.source in self.used or self.target in self.occupied or any(src==self.source or dst==self.target for src,col,dst in self.plan):
            messagebox.showwarning("Ячейки","Источник использован/назначен или назначение занято.");return
        self.plan.append((self.source,category,self.target));self.source=None;self.target=None;self.refresh()

    def remove(self):
        if self.busy or self.failed:return
        selected=self.table.selection()
        if selected:self.plan.pop(int(selected[0]));self.refresh()

    def clear(self):
        if not self.busy and not self.failed:self.plan.clear();self.refresh()

    def ask_worker(self,text):
        event=threading.Event();result=[];self.events.put(("ask",(text,event,result)));event.wait();return result[0]

    def launch(self,func):
        if self.busy or self.failed:return
        self.busy=True;self.status.set("Выполняется…")
        self.start_button.config(state="disabled");self.run_button.config(state="disabled")
        def worker():
            error=None
            try:func()
            except Exception as exc:error=str(exc);self.backend.fail(exc)
            self.events.put(("done",error))
        threading.Thread(target=worker,daemon=False).start()

    def execute(self):
        if self.busy or self.failed:return
        if not self.backend.ready:messagebox.showwarning("Запуск","Сначала выполните запуск / HOME.");return
        if not self.plan:messagebox.showwarning("План","Нет назначений.");return
        if not messagebox.askyesno("Подтверждение","Упаковки стоят согласно плану, указанные приёмные ячейки пустые, маршруты проверены. Выполнить?"):return
        plan=list(self.plan);self.backend.completed=[];self.launch(lambda:self.backend.run(plan))

    def poll(self):
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=="log":
                    self.logbox.config(state="normal");self.logbox.insert("end",value+"\n");self.logbox.see("end");self.logbox.config(state="disabled")
                elif kind=="ask":
                    text,event,result=value
                    try:result.append(messagebox.askyesno("Разрешение оператора",text))
                    finally:
                        if not result:result.append(False)
                        event.set()
                elif kind=="done":
                    self.busy=False
                    for src,col,dst in self.backend.completed:
                        self.used.add(src);self.occupied.add(dst)
                        if (src,col,dst) in self.plan:self.plan.remove((src,col,dst))
                    self.backend.completed=[];self.refresh()
                    if value:
                        self.failed=True;self.status.set("Ошибка — требуется проверка установки")
                        messagebox.showerror("Ошибка",value+"\nНовые команды заблокированы. Проверьте остановку и расположение упаковок.")
                    else:
                        self.status.set("Готов");self.start_button.config(state="normal");self.run_button.config(state="normal")
        except queue.Empty:pass
        self.root.after(100,self.poll)

    def close(self):
        if self.busy:messagebox.showwarning("Работа","Закрытие окна не останавливает робот. При необходимости используйте аппаратную аварийную кнопку.");return
        if messagebox.askyesno("Выход","Закрыть интерфейс? Приводы автоматически не отключаются."):self.root.destroy()

if __name__=="__main__":
    root=tk.Tk();App(root);root.mainloop()
