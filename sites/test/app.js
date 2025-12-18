(function(){
  // JS demo on home page (no persistence)
  var btn = document.getElementById("jsBtn");
  var out = document.getElementById("jsOut");
  if(btn && out){
    var clicks = 0;
    btn.addEventListener("click", function(){
      clicks += 1;
      out.textContent = "Clicked " + clicks + " time(s)";
    });
  }

  // Form preview (no submission, no storage)
  var form = document.getElementById("demoForm");
  var preview = document.getElementById("preview");
  if(form && preview){
    form.addEventListener("submit", function(e){
      e.preventDefault();
      var nameEl = document.getElementById("name");
      var prEl = document.getElementById("priority");
      var notesEl = document.getElementById("notes");
      var name = nameEl ? nameEl.value : "";
      var priority = prEl ? prEl.value : "";
      var notes = notesEl ? notesEl.value : "";
      preview.textContent =
        "Name: " + name + "\n" +
        "Priority: " + priority + "\n\n" +
        "Notes:\n" + notes;
    });
  }
})();
