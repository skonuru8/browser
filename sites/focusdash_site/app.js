function $(id){ return document.getElementById(id); }
function fmt2(n){ return String(n).padStart(2, "0"); }
function todayISO(){
  const d = new Date();
  return d.getFullYear() + "-" + fmt2(d.getMonth()+1) + "-" + fmt2(d.getDate());
}
function loadJSON(key, fallback){
  try{ const raw = localStorage.getItem(key); return raw ? JSON.parse(raw) : fallback; }
  catch(e){ return fallback; }
}
function saveJSON(key, value){
  try{ localStorage.setItem(key, JSON.stringify(value)); }catch(e){}
}
function updateKPIs(){
  if($("todayDate")) $("todayDate").textContent = todayISO();
  const tasks = loadJSON("fd_tasks", []);
  const planned = tasks.reduce((a,t)=>a+(t.minutes||0),0);
  const done = tasks.filter(t=>t.done).reduce((a,t)=>a+(t.minutes||0),0);
  if($("plannedMinutes")) $("plannedMinutes").textContent = planned + " min";
  if($("completedMinutes")) $("completedMinutes").textContent = done + " min";
}
function renderTasks(){
  const ul = $("taskList"); if(!ul) return;
  ul.innerHTML = "";
  const tasks = loadJSON("fd_tasks", []);
  tasks.slice(0,3).forEach((t, idx) => {
    const li = document.createElement("li"); li.className = "item";
    const label = document.createElement("label");
    const cb = document.createElement("input"); cb.type="checkbox"; cb.checked=!!t.done;
    cb.addEventListener("change", ()=>{ tasks[idx].done = cb.checked; saveJSON("fd_tasks", tasks); updateKPIs(); renderTasks(); });
    const sp = document.createElement("span"); sp.textContent = t.text;
    label.appendChild(cb); label.appendChild(sp);
    const small = document.createElement("small"); small.textContent = (t.minutes||25) + " min";
    li.appendChild(label); li.appendChild(small);
    ul.appendChild(li);
  });
}
function addTask(){
  const inp = $("taskInput"); if(!inp) return;
  const text = (inp.value||"").trim(); if(!text) return;
  const tasks = loadJSON("fd_tasks", []);
  tasks.unshift({text, done:false, minutes:25});
  saveJSON("fd_tasks", tasks); inp.value="";
  updateKPIs(); renderTasks();
}
let timerMode="focus"; let remaining=25*60; let tick=null;
function renderTimer(){
  if($("timerLabel")) $("timerLabel").textContent = timerMode==="focus" ? "Focus" : "Break";
  const m=Math.floor(remaining/60), s=remaining%60;
  if($("timerDisplay")) $("timerDisplay").textContent = fmt2(m)+":"+fmt2(s);
}
function setTimerFromInputs(){
  const f=$("focusMin"), b=$("breakMin");
  const fmin=f?Math.max(5,Math.min(90,parseInt(f.value||"25",10))):25;
  const bmin=b?Math.max(1,Math.min(30,parseInt(b.value||"5",10))):5;
  remaining = (timerMode==="focus"?fmin:bmin)*60;
  renderTimer();
}
function step(){
  remaining = Math.max(0, remaining-1);
  renderTimer();
  if(remaining===0){ timerMode = timerMode==="focus" ? "break" : "focus"; setTimerFromInputs(); }
}
function startTimer(){ if(tick) return; tick=setInterval(step,1000); }
function pauseTimer(){ if(!tick) return; clearInterval(tick); tick=null; }
function resetTimer(){ pauseTimer(); setTimerFromInputs(); }
function renderProjects(){
  const wrap=$("projectsWrap"); if(!wrap) return;
  wrap.innerHTML="";
  const projects=loadJSON("fd_projects", []);
  projects.forEach((p, idx)=>{
    const card=document.createElement("div"); card.className="project";
    const h=document.createElement("h3"); h.textContent=p.name; card.appendChild(h);
    const row=document.createElement("div"); row.className="row";
    const inp=document.createElement("input"); inp.className="text"; inp.placeholder="Add milestone";
    const btn=document.createElement("button"); btn.textContent="Add milestone";
    btn.addEventListener("click", ()=>{
      const txt=(inp.value||"").trim(); if(!txt) return;
      projects[idx].milestones = projects[idx].milestones || [];
      projects[idx].milestones.unshift({text:txt, done:false});
      saveJSON("fd_projects", projects); renderProjects();
    });
    row.appendChild(inp); row.appendChild(btn); card.appendChild(row);
    wrap.appendChild(card);
  });
}
function addProject(){
  const inp=$("projName"); if(!inp) return;
  const name=(inp.value||"").trim(); if(!name) return;
  const projects=loadJSON("fd_projects", []);
  projects.unshift({name, milestones:[]}); saveJSON("fd_projects", projects);
  inp.value=""; renderProjects();
}
function renderHabits(){
  const wrap=$("habitsWrap"); if(!wrap) return;
  wrap.innerHTML="";
  const habits=loadJSON("fd_habits", []);
  const today=todayISO();
  habits.forEach((h, idx)=>{
    const card=document.createElement("div"); card.className="project";
    const h3=document.createElement("h3"); h3.textContent=h.name; card.appendChild(h3);
    const row=document.createElement("div"); row.className="row";
    const btn=document.createElement("button");
    btn.textContent = (h.lastDone===today) ? "Done today ✓" : "Done today";
    btn.className = (h.lastDone===today) ? "secondary" : "";
    btn.addEventListener("click", ()=>{
      const hs=loadJSON("fd_habits", []);
      if(hs[idx].lastDone===today) return;
      hs[idx].lastDone=today; hs[idx].streak=(hs[idx].streak||0)+1;
      saveJSON("fd_habits", hs); renderHabits();
    });
    row.appendChild(btn); card.appendChild(row); wrap.appendChild(card);
  });
}
function addHabit(){
  const inp=$("habitName"); if(!inp) return;
  const name=(inp.value||"").trim(); if(!name) return;
  const habits=loadJSON("fd_habits", []);
  habits.unshift({name, streak:0, lastDone:null});
  saveJSON("fd_habits", habits); inp.value=""; renderHabits();
}
document.addEventListener("DOMContentLoaded", ()=>{
  updateKPIs(); renderTasks(); renderProjects(); renderHabits(); renderTimer(); setTimerFromInputs();
  if($("addTaskBtn")) $("addTaskBtn").addEventListener("click", addTask);
  if($("taskInput")) $("taskInput").addEventListener("keydown",(e)=>{ if(e.key==="Enter") addTask(); });
  if($("clearDoneBtn")) $("clearDoneBtn").addEventListener("click", ()=>{
    const tasks=loadJSON("fd_tasks", []).filter(t=>!t.done); saveJSON("fd_tasks", tasks); updateKPIs(); renderTasks();
  });
  if($("wipeAllBtn")) $("wipeAllBtn").addEventListener("click", ()=>{ saveJSON("fd_tasks", []); updateKPIs(); renderTasks(); });
  if($("startBtn")) $("startBtn").addEventListener("click", startTimer);
  if($("pauseBtn")) $("pauseBtn").addEventListener("click", pauseTimer);
  if($("resetBtn")) $("resetBtn").addEventListener("click", resetTimer);
  if($("focusMin")) $("focusMin").addEventListener("change", setTimerFromInputs);
  if($("breakMin")) $("breakMin").addEventListener("change", setTimerFromInputs);
  if($("addProjBtn")) $("addProjBtn").addEventListener("click", addProject);
  if($("addHabitBtn")) $("addHabitBtn").addEventListener("click", addHabit);
});
