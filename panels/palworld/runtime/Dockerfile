FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl gosu libc6-i386 lib32gcc-s1 lib32stdc++6 libatomic1 \
    libicu74 libpulse0 libsdl2-2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system palworld \
    && useradd --system --gid palworld --create-home --home-dir /home/palworld \
       --shell /bin/bash palworld \
    && mkdir -p /opt/steamcmd /home/palworld/.steam/sdk64 /server \
    && curl --fail --show-error --location --retry 3 \
       https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz \
       | tar -xz -C /opt/steamcmd \
    && chown -R palworld:palworld /opt/steamcmd /home/palworld /server

COPY entrypoint.sh /usr/local/bin/palworld-entrypoint
RUN chmod 755 /usr/local/bin/palworld-entrypoint

ENV SteamAppId=2394010
ENV HOME=/home/palworld
ENV USER=palworld
WORKDIR /server
EXPOSE 8211/udp 8212/tcp 25575/tcp
STOPSIGNAL SIGINT
ENTRYPOINT ["/usr/local/bin/palworld-entrypoint"]
CMD ["serve"]
