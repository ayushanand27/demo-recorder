# Docker se chalao

Build (ek baar):
    docker build -t demo-recorder .

Run (Windows PowerShell, folder jisme tumhari script hai):
    docker run --rm -v ${PWD}:/work demo-recorder examples/demo.json

Video usi folder me aayegi (JSON ke "out" naam se).

Apna localhost app record karna ho to script me
`http://host.docker.internal:3000` use karo (localhost nahi).
Edge-TTS ko internet chahiye.
