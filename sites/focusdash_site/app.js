function $(id){ return document.getElementById(id); }
function fmt2(n){ n = Number(n) || 0; return (n < 10 ? "0" : "") + String(n); }

function todayISO(){
  var d = new Date();
  return d.getFullYear() + "-" + fmt2(d.getMonth()+1) + "-" + fmt2(d.getDate());
}

function loadJSON(key, fallback){
  try{
    var raw = (typeof localStorage !== "undefined") ? localStorage.getItem(key) : null;
    return raw ? JSON.parse(raw) : fallback;
  } catch(e){ return fallback; }
}
function saveJSON(key, value){
  try{
    if (typeof localStorage !== "undefined") localStorage.setItem(key, JSON.stringify(value));
  } catch(e){}
}

function updateKPIs(){
  var el = $("todayDate");
  if(el) el.textContent = todayISO();
  var tasks = loadJSON("fd_tasks", []);
  var planned = 0, done = 0, i;
  for(i=0;i<tasks.length;i++){
    planned += (tasks[i].minutes||0);
    if(tasks[i].done) done += (tasks[i].minutes||0);
  }
  el = $("plannedMinutes"); if(el) el.textContent = planned + " min";
  el = $("completedMinutes"); if(el) el.textContent = done + " min";
}

var timerMode="focus", remaining=25*60, tick=null;

function renderTimer(){
  var label = $("timerLabel");
  if(label) label.textContent = (timerMode==="focus" ? "Focus" : "Break");
  var m=Math.floor(remaining/60), s=remaining%60;
  var disp = $("timerDisplay");
  if(disp) disp.textContent = fmt2(m) + ":" + fmt2(s);
}

function setTimerFromInputs(){
  var f=$("focusMin"), b=$("breakMin");
  var fmin = f ? parseInt(f.value||"25",10) : 25;
  var bmin = b ? parseInt(b.value||"5",10) : 5;
  if(!fmin || fmin<5) fmin=25; if(fmin>90) fmin=90;
  if(!bmin || bmin<1) bmin=5;  if(bmin>30) bmin=30;
  remaining = (timerMode==="focus" ? fmin : bmin) * 60;
  renderTimer();
}

function step(){
  remaining = Math.max(0, remaining-1);
  renderTimer();
  if(remaining===0){
    timerMode = (timerMode==="focus" ? "break" : "focus");
    setTimerFromInputs();
  }
}

function startTimer(){ if(tick) return; tick=setInterval(step,1000); }
function pauseTimer(){ if(!tick) return; clearInterval(tick); tick=null; }
function resetTimer(){ pauseTimer(); setTimerFromInputs(); }

// keep your old functions, but DON’T let them block wiring buttons:
function renderTasks(){ /* your existing renderTasks */ }
function renderProjects(){ /* your existing renderProjects */ }
function renderHabits(){ /* your existing renderHabits */ }
function addTask(){ /* your existing addTask */ }
function addProject(){ /* your existing addProject */ }
function addHabit(){ /* your existing addHabit */ }

document.addEventListener("DOMContentLoaded", function(){
  // Wire critical buttons FIRST
  var el;
  el = $("startBtn"); if(el) el.addEventListener("click", startTimer);
  el = $("pauseBtn"); if(el) el.addEventListener("click", pauseTimer);
  el = $("resetBtn"); if(el) el.addEventListener("click", resetTimer);

  el = $("focusMin"); if(el) el.addEventListener("change", setTimerFromInputs);
  el = $("breakMin"); if(el) el.addEventListener("change", setTimerFromInputs);

  // Now do rendering, but don't let it kill the page
  try { updateKPIs(); } catch(e) {}
  try { renderTimer(); setTimerFromInputs(); } catch(e) {}
  try { renderTasks(); } catch(e) {}
  try { renderProjects(); } catch(e) {}
  try { renderHabits(); } catch(e) {}
});
