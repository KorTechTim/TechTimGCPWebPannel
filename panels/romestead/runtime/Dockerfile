FROM mcr.microsoft.com/dotnet/runtime:8.0-noble

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl gosu libc6-i386 lib32gcc-s1 lib32stdc++6 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system romestead \
    && useradd --system --gid romestead --create-home --home-dir /home/romestead \
       --shell /bin/bash romestead \
    && mkdir -p /opt/steamcmd /home/romestead/.steam/sdk64 /server \
    && curl --fail --show-error --location --retry 3 \
       https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz \
       | tar -xz -C /opt/steamcmd \
    && chown -R romestead:romestead /opt/steamcmd /home/romestead /server

COPY entrypoint.sh /usr/local/bin/romestead-entrypoint
RUN chmod 755 /usr/local/bin/romestead-entrypoint

ENV SteamAppId=4763510
ENV HOME=/home/romestead
ENV USER=romestead
WORKDIR /server
EXPOSE 8050/udp
STOPSIGNAL SIGINT
ENTRYPOINT ["/usr/local/bin/romestead-entrypoint"]
CMD ["serve"]
