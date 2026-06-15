# syntax=docker/dockerfile:1
FROM debian:trixie

ARG LAB_USER

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# udev is needed for booting a "real" VM, setting up the ttyS0 console properly
# kmod is needed for modprobing modules
RUN <<EOF
set -eu

apt-get update
apt-get upgrade -y

apt-get install --no-install-recommends -y \
  bash-completion \
  bzip2 \
  ca-certificates \
  curl \
  dbus \
  dnsutils \
  file \
  gettext-base \
  git \
  gnupg \
  htop \
  iputils-ping \
  kmod \
  locales \
  lsb-release \
  lsof \
  man \
  mtr \
  netcat-openbsd \
  net-tools \
  psmisc \
  socat \
  sudo \
  systemd \
  traceroute \
  tree \
  udev \
  unzip \
  vim \
  wget \
  tmux \
  openssh-server

# Doesn't seem to be needed and produces extra noise in journald.
systemctl mask networkd-dispatcher.service

rm -rf /etc/update-motd.d/*
rm -rf /etc/motd
rm -f /.dockerenv

# Create the following files, but unset them.
echo "" > /etc/machine-id && echo "" > /var/lib/dbus/machine-id

echo "root:root" | chpasswd

apt-get autoremove -y
apt-get autoclean -y
apt-get clean -y
rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
EOF

RUN <<EOF
set -eu

cat >> /etc/ssh/sshd_config <<EOT
HostKey /etc/ssh/ssh_host_ed25519_key
AuthenticationMethods publickey
PrintLastLog no
AddressFamily inet
UseDNS no
MaxAuthTries 50
EOT

systemctl mask sshd-keygen@.service
systemctl mask sshd-keygen.target

# cat >> /lib/systemd/system/ssh.socket <<EOT
#
# [Socket]
# ListenStream=vsock::22
# Accept=yes
# EOT

rm -f /etc/ssh/ssh_host_*
EOF

RUN <<EOF
set -eu

USER_ID=1001
USERNAME=$LAB_USER
PASSWORD=$LAB_USER
adduser --disabled-password --gecos "" --shell $(which bash) --uid $USER_ID $USERNAME

echo "$USERNAME:$PASSWORD" | chpasswd

usermod -aG sudo $USERNAME

echo "$USERNAME ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers.d/$USERNAME

chmod 0440 /etc/sudoers.d/$USERNAME
EOF


USER $LAB_USER
ENV HOME=/home/$LAB_USER

COPY --chown=$LAB_USER:$LAB_USER .vimrc $HOME
COPY --chown=$LAB_USER:$LAB_USER .tmux.conf $HOME

