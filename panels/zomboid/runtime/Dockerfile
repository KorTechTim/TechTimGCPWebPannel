FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl gosu lib32gcc-s1 lib32stdc++6 libatomic1 libpulse0 \
    libsdl2-2.0-0 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd --system zomboid \
    && useradd --system --gid zomboid --create-home --home-dir /home/zomboid --shell /bin/bash zomboid \
    && mkdir -p /opt/steamcmd /home/zomboid/Zomboid /home/zomboid/.steam/sdk64 /server \
    && curl --fail --show-error --location --retry 3 \
       https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz \
       | tar -xz -C /opt/steamcmd \
    && chown -R zomboid:zomboid /opt/steamcmd /home/zomboid /server
COPY entrypoint.sh /usr/local/bin/zomboid-entrypoint
RUN chmod 755 /usr/local/bin/zomboid-entrypoint
ENV SteamAppId=108600 HOME=/home/zomboid USER=zomboid
WORKDIR /server
EXPOSE 16261/udp 16262/udp 27015/tcp
STOPSIGNAL SIGTERM
ENTRYPOINT ["/usr/local/bin/zomboid-entrypoint"]
CMD ["serve", "8", ""]
