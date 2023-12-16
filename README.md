# DesktopEnv: An Environment towards Human-like Computer Task Mastery

## Setup guide

### For members of the team
1. Download OS image
   1. Download kubuntu from <https://kubuntu.org/getkubuntu/>
   2. Download ubuntu from <https://ubuntu.com/download/desktop>
      1. If mac OS, use <https://cdimage.ubuntu.com/jammy/daily-live/current/jammy-desktop-arm64.iso>
   3. Download Windows from <https://www.microsoft.com/en-au/software-download/windows10ISO>
   4. ~~Download MacOS~~ (Not possible to download legally)
2. Setup virtual machine
   1. Create `Host Only Adapter` and add it to the network adapter in the settings
3. Set up bridge for connecting to VM
   1. Option 1: Install [xdotool](https://github.com/jordansissel/xdotool) on VM
   2. Option 2: Install [mouse](https://github.com/boppreh/mouse/)
4. Set up SSH server on VM | [Guide](./SERVER_SETUP.md)
5. Install screenshot tool (in vm)
   1. `sudo apt install imagemagick-6.q16hdri`
   2. `DISPLAY=:0 import -window root screenshot.png`
6. Get screenshot
   1. `scp user@192.168.7.128:~/screenshot.png screenshot.png`
   2. `rm -rf ~/screenshot.png`
7. Set up python and install [mouse](https://github.com/boppreh/mouse/) and [keyboard](https://github.com/jordansissel/xdotool)

### For users of the environment
todo

## Road map (Proposed)

- [x] Explore VMWare, and whether it can be connected and control through mouse package
- [x] Explore Windows and MacOS, whether it can be installed
  - MacOS is closed source and cannot be legally installed
  - Windows is available legally and can be installed
- [x] Build gym-like python interface for controlling the VM
- [ ] Make configuration much easier from code perspective
  - [ ] README
  - [ ] Make it easier to install the dependencies
  - [ ] Make it easier to install the VM
  - [ ] Make it easier to set up the VM
- [ ] Recording of actions (mouse movement, click, keyboard) for human to annotate, and we can replay it
  - [ ] This part may be conflict with work from [Aran Komatsuzaki](https://twitter.com/arankomatsuzaki) team, a.k.a. [Duck AI](https://duckai.org/)
- [ ] Build a simple task, e.g. open a browser, open a website, click on a button, and close the browser
- [ ] Set up a pipeline and build agents implementation (zero-shot) for the task
- [ ] Start to design on which tasks inside the DesktopENv to focus on, start to wrap up the environment to be public
- [ ] Start to annotate the examples for training and testing
