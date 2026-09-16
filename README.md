# ircbanbot
Python script that allows you to upload and download glines from an ngircd server

A gline is an irc mechanism that allows you to ban a given user from an irc
server.  Although the ngircd daemon supports glines, the gline info is only
stored in the runtime process: ngircd doesn't have an option to store glines in
a configuration file. If you restart the server, you will lose your current
glines.

This script allows you to both download and upload ngircd glines to/from a JSON
file.  You can add it as a ExecStartPost script so that every time you start
your server, the glines will be restored.

## Requirements

  * [ngircd server](https://github.com/ngircd/ngircd)
  * root access to ngircd and host
  * python 3

## Installation

### ngirc operator account
You will need to have an **operator account** on ngircd for ircbanbot as
only operators can manage glines in the server.

Here's a sample operator account:

```
  [Operator]
        Name = banbot
        Password = change,me
        Mask = *!banbot@*
```

### ircbanbot script and virtual environment

In this section we show how to install ircbanbot and a python
virtual environment (.venv) in that same directory. Adjust
these steps as needed in your own environment.

```
git clone https://github.com/jkbzh/ircbanbot.git
cd ircbanbot
```

#### create and activate virtual environment
```
python3 -m venv .venv
source .venv/bin/activate
```
#### install package dependencies
`pip install --upgrade -r requirements.txt`

Copy ircbanbot.conf.dist to ircbanbot.conf and edit it.
You'll need to set up an irc operator account on ngircd
that will be used by ircbanbot. Here we assume you install
the configuration file to /etc/ircbanbot.conf

#### configure ircbanbot

Make a copy of ircbanbot.conf.dist and edit it. You'll
need to enter the irc server and irc server operator
account parameters. 

The` GLINE_FILE` option points to the file used to retrieve / store the gline
data.

`cp ircbanbot.conf.dist /etc/ircbanbot.conf`
`editor ircbanbot.conf`

```
BOT\_NICKNAME="banbot"
IRC\_SERVER="irc.example.org"
IRC\_PORT=669

# wait n seconds for irc server to be ready
SERVER\_WAIT=0
 
# banbot account on ngircd
# account name and password must be in sync
IRC\_OPERATOR_PASSWORD="change,me"
ACCOUNT\_NAME="banbot"
ACCOUNT\_PASSWORD="change,me"
 
# path to file  used to store / upload glines
# path must exist and be accessible to script
GLINE\_FILE="/var/lib/ircbanbot/glines.json"
```
## test your setup

We'll create a gline on ngircd, download the glines, delete the gline on the
server, and upload the glines back to the server. 

Note that this test will download all the existing glines in your server,
delete them, and upload them. If you're not sure about your configuration, do
the setup test on a non-production ngircd server.

On ngircd, as an operator, add a gline to ngircd using your operator account

`/GLINE foo!~bar@*.* 0 :unauthorized bot`

Check it's there

`/STATS g`

Now download the glines using ircbanbot (your virtual environment has to be active)

`ircbanbot.py -f /etc/ircbanbot.conf -d`

Check the download worked

`cat /var/log/glines.json`

On ngircd, delete the gline you created

`/GLINE foo!~bar@*.*`

Check it's gone

`/STATS g`

Now restore the glines ircbanbot. Note that restoring the glines will delete
all existing glines on the server and recreate them using the data in the
`glines.json` file.

`ircbanbot.py -f /etc/ircbanbot.conf -u`

Check the gline was restored

`/STATS g`

## integrating ircbanbot into your ngircd systemd setup

In this setup, the `glines.json` file is the primary source of the glines for
the server. They are uploaded to the ngircd server each time the server
restarts or whenever the file is edited by means of the ircbanbot script. This
guarantees that you can restart your server without having to dowload the
runtime gline status from time to time to avoid losing it.

Here below we assume that you have installed `ircbanbot.py` under
`/usr/local/sbin/ircbanbot/` and created its virtual environment in that same
directory.

We'll now make a wrapper script that will launch ircbanbot from within the
python virtual environment and park it in /usr/local/sbin. We'll call this
script `ircbanbot-wrapper`.


`#!/bin/env bash
exec /usr/local/sbin/ircbanbot/.venv/bin/python3 /usr/local/sbin/ircbanbot/ircbanbot.py "$@" -f /etc/ircbanbot.conf`

Next step is to edit the ngircd systemd unit and add an `ExecStartPost` directive
to execute the `ircbanbot-wrapper` once ngircd is ready.


`systemctl edit ngircd`

`ExecStartPost=-/usr/local/sbin/ircbanbot-wrapper -u`

NOTE: If ircbanbot is running before ngircd is ready, you can add a delay to
the script using the ircbanbot `SERVER\_WAIT` configuration option.

These changes will ensure that each time your ngircd daemon is started, the glines
will be uploaded.

# glines.json format

The file format is very basic and follows the gline command syntax. Here
is a sample entry indefinitely banning a user with nickname `foo` connecting from any
user account called `bar`, regardless of the hostname. The message is the notification
a user gets when he is banned.

```
[
 {
  "msg":"unauthorized bot",
  "time":"0",
  "user":"**foo**!**bar**@\*.\*"
 }
]
```
