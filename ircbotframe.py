import socket
import threading
import re
import time

class ircOutputBuffer:
    # Delays consecutive messages by at least 1 second.
    # This prevents the bot spamming the IRC server.
    def __init__(self, irc):
        self.waiting = False
        self.irc = irc
        self.queue = []
    def __pop(self):
        if len(self.queue) == 0:
            self.waiting = False
        else:
            self.sendImmediately(self.queue[0])
            self.queue = self.queue[1:]
            self.__startPopTimer()
    def __startPopTimer(self):
        self.timer = threading.Timer(1, self.__pop)
        self.timer.start()
    def sendBuffered(self, string):
        # Sends the given string after the rest of the messages in the buffer.
        # There is a 1 second gap between each message.
        if self.waiting:
            self.queue.append(string)
        else:
            self.waiting = True
            self.sendImmediately(string)
            self.__startPopTimer()
    def sendImmediately(self, string):
        # Sends the given string without buffering.
        print("Sending \"" + string + "\"")
        self.irc.send(bytes(string) + b"\r\n")

class ircInputBuffer:
    # Keeps a record of the last line fragment received by the socket which is usually not a complete line.
    # It is prepended onto the next block of data to make a complete line.
    def __init__(self, irc):
        self.buffer = ""
        self.irc = irc
        self.lines = []
    def __recv(self):
        # Receives new data from the socket and splits it into lines.
        # Last (incomplete) line is kept for buffer purposes.
        try:
            data = self.buffer + self.irc.recv(4096)
        except socket.error, msg:
            raise socket.error, msg
        self.lines += data.split(b"\r\n")
        self.buffer = self.lines[len(self.lines) - 1]
        self.lines = self.lines[:len(self.lines) - 1]
    def getLine(self):
        # Returns the next line of IRC received by the socket.
        # Converts the received string to standard string format before returning.
        while len(self.lines) == 0:
            try:
                self.__recv()
            except socket.error, msg:
                raise socket.error, msg
            time.sleep(1);
        line = self.lines[0]
        self.lines = self.lines[1:]
        return str(line)

class ircBot:
    def __init__(self, network, port, name, description):
        self.keepGoing = True
        self.name = name
        self.desc = description
        self.network = network
        self.port = port
        self.identifyNickCommands = []
        self.serverName = ""
        self.binds = []
    # PRIVATE FUNCTIONS
    def __identAccept(self, nick):
        # Calls the given "approved" callback.
        for (nickName, accept, acceptParams, reject, rejectParams) in self.identifyNickCommands:
            if nickName == nick:
                print nickName + " has been verified."
                accept(self, *acceptParams)
                self.identifyNickCommands.remove((nickName, accept, acceptParams, reject, rejectParams))
    def __identReject(self, nick):
        # Calls the given "denied" callback.
        for (nickName, accept, acceptParams, reject, rejectParams) in self.identifyNickCommands:
            if nickName == nick:
                print nickName + " could not be verified."
                reject(self, *rejectParams)
                self.identifyNickCommands.remove((nickName, accept, acceptParams, reject, rejectParams))
    def __callBind(self, msgtype, sender, headers, message):
        # Calls the function associated with the given msgtype.
        for (messageType, callback) in self.binds:
            if (messageType == msgtype):
                callback(self, sender, headers, message)
    def __processLine(self, line):
        # Does most of the parsing of the line received from the IRC network.
        #print line
        lineParts = line[1:].split(":")
        headers = lineParts[0].split()
        message = ""
        if len(lineParts) > 1:
            message = line[1:].split(":")[1]
        if self.serverName == "":
            self.serverName = headers[0]
        sender = headers[0]
        if sender == self.serverName:
            #print "Received " + headers[1] + " from the server."
            if headers[1] == "307" and len(headers) >= 4:
                self.__identAccept(headers[3])
            if headers[1] == "318" and len(headers) >= 4:
                self.__identReject(headers[3])
            self.__callBind(headers[1], sender, headers[2:], message)
        else:
            cut = headers[0].find('!')
            if cut != -1:
                sender = sender[:cut]
            msgtype = headers[1]
            if msgtype == "PRIVMSG" and message.startswith("ACTION ") and message.endswith(""):
                msgtpye = "ACTION"
            print "Received " + msgtype + " from " + sender + "."
            self.__callBind(msgtype, sender, headers[2:], message)
    # PUBLIC FUNCTIONS
    def ban(self, nick):
        print "Banning " + nick + "..."
    def bind(self, msgtype, callback):
        for i in xrange(0, len(self.binds)):
            if self.binds[i][0] == msgtype:
                self.binds.remove(i)
        self.binds.append((msgtype, callback))
    def connect(self):
        print "Connecting..."
        self.irc = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.irc.connect((self.network, self.port))
        self.inBuf = ircInputBuffer(self.irc)
        self.outBuf = ircOutputBuffer(self.irc)
        self.outBuf.sendBuffered("NICK " + self.name)
        self.outBuf.sendBuffered("USER " + self.name + " " + self.name + " " + self.name + " :" + self.desc)
    def disconnect(self, qMessage):
        print "Disconnecting..."
        self.outBuf.sendBuffered("QUIT :" + qMessage)
        self.irc.close()
    def identify(self, nick, approvedFunc, approvedParams, deniedFunc, deniedParams):
        print "Verifying " + nick + "..."
        self.identifyNickCommands += [(nick, approvedFunc, approvedParams, deniedFunc, deniedParams)]
        self.outBuf.sendBuffered("WHOIS " + nick)
    def join(self, channel):
        print "Joining " + channel + "..."
        self.outBuf.sendBuffered("JOIN " + channel)
    def kick(self, nick):
        print "Kicking " + nick + "..."
    def reconnect(self):
        self.disconnect("Reconnecting")
        print "Pausing before reconnecting..."
        time.sleep(5)
        self.connect()
    def run(self):
        while self.keepGoing:
            line = ""
            while len(line) == 0:
                try:
                    line = self.inBuf.getLine()
                except socket.error, msg:
                    print msg
                    self.reconnect()
            if line.startswith("PING"):
                self.outBuf.sendImmediately("PONG " + line.split()[1])
            else:
                self.__processLine(line)
    def say(self, recipient, message):
        self.outBuf.sendBuffered("PRIVMSG " + recipient + " :" + message)  
    def send(self, string):
        self.outBuf.sendBuffered(string)
    def stop(self):
        self.keepGoing = False

