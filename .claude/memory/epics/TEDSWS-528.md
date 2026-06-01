TEDSWS-528: Remove references to Meaningfy in source code repositories

References to Meaningfy should be removed from the source code repositories. There are 
for example references pointing to Meaningfy emails for more information on the system or development attributions to Meanigfy. 

This project was developed as an open source for the Publications Office of the European Union.


Give me the command that finds all the mentions to Meaningfy in the source code repositories, so that I can analyse them afterwards.

Filter out the folders: 
- .venv
- .claude
- github
- test
- .idea


grep -rniI \
    --exclude-dir=.git \
    --exclude-dir=.venv \
    --exclude-dir=.claude \
    --exclude-dir=.github \
    --exclude-dir=.idea \
    --exclude-dir=node_modules \
    "meaningfy" .

---
