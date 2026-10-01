from math import pi
ROBOT_IP="192.168.2.100"
LAMP_IP="192.168.2.101"
HOME=[0.5,-0.12,0.3,pi,0,pi/2]
HOME_JOINTS=[v*pi/180 for v in (0,15,27,47,90,0)]
ORIENTATION=[pi,0,pi/2]
Z_PLACE=0.03
Z_TRANSFER=0.20
GRIP_DELAY=0.5
RELEASE_DELAY=0.5
RESET_DELAY=5
TIMEOUT=120
POLL_INTERVAL=0.1
TOTAL_PACKAGES=6
POSITION_TOLERANCE=0.01
ANGLE_TOLERANCE=0.1*pi/180
SOURCE={"I":(.59,-.1),"II":(.59,.005),"III":(.59,.11),
"IV":(.5,-.1),"V":(.5,.005),"VI":(.5,.11),
"VII":(.41,-.1),"VIII":(.41,.005),"IX":(.41,.11)}
TARGET={1:(.6,.35),2:(.6,.46),3:(.6,.57),4:(.5,.35),5:(.5,.46),6:(.5,.57),
7:(.4,.35),8:(.4,.46),9:(.4,.57),10:(.59,-.57),11:(.59,-.455),12:(.59,-.34),
13:(.5,-.57),14:(.5,-.455),15:(.5,-.34),16:(.41,-.57),17:(.41,-.455),18:(.41,-.34)}
LED={"start":"0001","checking":"1000","moving":"0010","ready":"0100","error":"0001"}
